"""The Composio and Browserbase adapters, against a mock HTTP transport."""

import json
from collections.abc import Callable

import httpx
import pytest

from app.domain.errors import IntegrationError
from app.integrations.browserbase import BrowserbaseClient, parse_run
from app.integrations.composio import ComposioClient, ComposioNotFoundError, ComposioRejectedError

Handler = Callable[[httpx.Request], httpx.Response]
SECRET_ECHO = "provider says: your note 'buy milk' was rejected"


def http_client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def composio(handler: Handler) -> ComposioClient:
    return ComposioClient(
        http_client(handler), api_key="cmp_key", base_url="https://backend.composio.test"
    )


def browserbase(handler: Handler) -> BrowserbaseClient:
    return BrowserbaseClient(
        http_client(handler), api_key="bb_key", base_url="https://api.browserbase.test"
    )


# --- Composio --------------------------------------------------------------------------


async def test_active_accounts_are_listed_for_the_user_with_the_project_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "ca_1",
                        "status": "ACTIVE",
                        "toolkit": {"slug": "Gmail"},
                        "auth_config": {"id": "ac_1"},
                        "data": {"email": "ada@example.com"},
                    },
                    {"status": "ACTIVE"},
                ]
            },
        )

    accounts = await composio(handler).list_active_accounts("user-1")

    request = seen[0]
    assert request.url.path == "/api/v3.1/connected_accounts"
    assert dict(request.url.params) == {"user_ids": "user-1", "statuses": "ACTIVE"}
    assert request.headers["x-api-key"] == "cmp_key"
    assert len(accounts) == 1
    account = accounts[0]
    assert (account.id, account.toolkit_slug, account.auth_config_id) == ("ca_1", "gmail", "ac_1")
    assert (account.email, account.label) == ("ada@example.com", "ada@example.com")


async def test_a_connect_link_is_started_with_the_callback() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "link_1",
                "redirect_url": "https://connect.composio.dev/link/lk_1",
                "connected_account_id": "ca_9",
            },
        )

    link = await composio(handler).link_account("user-1", "ac_1", callback_url="memory://tools")

    assert bodies == [
        {"auth_config_id": "ac_1", "user_id": "user-1", "callback_url": "memory://tools"}
    ]
    assert (link.request_id, link.connected_account_id) == ("link_1", "ca_9")
    assert link.redirect_url == "https://connect.composio.dev/link/lk_1"


async def test_a_link_without_an_address_is_an_error() -> None:
    client = composio(lambda request: httpx.Response(200, json={"id": "link_1"}))

    with pytest.raises(IntegrationError, match="without an address"):
        await client.link_account("user-1", "ac_1", callback_url=None)


async def test_tool_sessions_are_scoped_to_one_toolkit_and_its_accounts() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"session_id": "trs_1"})

    session_id = await composio(handler).create_session("user-1", "slack", ["ca_1", "ca_2"])

    assert session_id == "trs_1"
    body = bodies[0]
    assert body["toolkits"] == {"enable": ["slack"]}
    assert body["connected_accounts"] == {"slack": ["ca_1", "ca_2"]}
    assert body["manage_connections"] == {"enable": False}


async def test_search_results_list_primary_tools_first_with_their_schemas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3.1/tool_router/session/trs_1/search"
        return httpx.Response(
            200,
            json={
                "results": [{"primary_tool_slugs": ["SLACK_SEND_MESSAGE"]}],
                "tool_schemas": {
                    "SLACK_LIST_CHANNELS": {"description": "List channels"},
                    "SLACK_SEND_MESSAGE": {
                        "description": "Send",
                        "input_parameters": {"type": "object"},
                    },
                },
            },
        )

    matches = await composio(handler).search_tools("trs_1", "post a message")

    assert [match.slug for match in matches] == ["SLACK_SEND_MESSAGE", "SLACK_LIST_CHANNELS"]
    assert matches[0].input_schema == {"type": "object"}


async def test_an_execution_reports_success_and_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {
            "tool_slug": "SLACK_SEND_MESSAGE",
            "arguments": {"channel": "#general", "text": "hi"},
        }
        return httpx.Response(200, json={"successful": True, "data": {"ts": "1"}, "error": None})

    result = await composio(handler).execute_tool(
        "trs_1", "SLACK_SEND_MESSAGE", {"channel": "#general", "text": "hi"}
    )

    assert (result.successful, result.data, result.error) == (True, {"ts": "1"}, None)


async def test_a_missing_record_is_its_own_error() -> None:
    client = composio(lambda request: httpx.Response(404, json={"message": SECRET_ECHO}))

    with pytest.raises(ComposioNotFoundError):
        await client.get_account("ca_gone")


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "rejected the API key"), (403, "rejected the API key"), (500, "HTTP 500")],
)
async def test_failures_are_described_without_echoing_the_provider(
    status: int, expected: str
) -> None:
    client = composio(lambda request: httpx.Response(status, json={"message": SECRET_ECHO}))

    with pytest.raises(IntegrationError) as caught:
        await client.list_active_accounts("user-1")

    assert expected in caught.value.message
    assert "buy milk" not in caught.value.message


@pytest.mark.parametrize("status", [400, 409, 422])
async def test_a_refused_request_carries_its_status(status: int) -> None:
    client = composio(lambda request: httpx.Response(status, json={"message": SECRET_ECHO}))

    with pytest.raises(ComposioRejectedError) as caught:
        await client.list_active_accounts("user-1")

    assert caught.value.http_status == status
    assert caught.value.message == f"Composio: rejected the request (HTTP {status})."


async def test_an_unreachable_service_is_an_integration_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(IntegrationError, match="could not be reached"):
        await composio(handler).list_active_accounts("user-1")


# --- Browserbase -----------------------------------------------------------------------


async def test_an_agent_run_asks_for_a_structured_result() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"runId": "run_1", "status": "RUNNING"})

    run = await browserbase(handler).start_run("Find the price")

    request = seen[0]
    assert request.url.path == "/v1/agents/runs"
    assert request.headers["X-BB-API-Key"] == "bb_key"
    body = json.loads(request.content)
    assert body["task"] == "Find the price"
    assert set(body["resultSchema"]["properties"]) == {"summary", "sourceUrl", "loginRequired"}
    assert (run.run_id, run.status, run.finished) == ("run_1", "RUNNING", False)


async def test_the_live_view_is_the_fullscreen_debugger() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/sessions/bb_1/debug"
        return httpx.Response(
            200,
            json={
                "debuggerFullscreenUrl": "https://live.browserbase.com/full",
                "debuggerUrl": "https://live.browserbase.com/plain",
            },
        )

    assert await browserbase(handler).live_view_url("bb_1") == "https://live.browserbase.com/full"


def test_a_finished_run_carries_its_result() -> None:
    run = parse_run(
        {
            "id": "run_1",
            "status": "completed",
            "sessionId": "bb_1",
            "result": {
                "summary": "999 dollars",
                "sourceUrl": "https://x.test",
                "loginRequired": False,
            },
        }
    )

    assert (run.status, run.finished, run.summary, run.source_url) == (
        "COMPLETED",
        True,
        "999 dollars",
        "https://x.test",
    )


def test_a_run_without_an_id_is_rejected() -> None:
    with pytest.raises(IntegrationError):
        parse_run({"status": "RUNNING"})


async def test_an_account_is_read_and_deleted_by_id() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"id": "ca_1", "status": "initiated", "alias": "Work"})

    client = composio(handler)
    account = await client.get_account("ca_1")
    await client.delete_account("ca_1")

    assert (account.status, account.label) == ("INITIATED", "Work")
    assert seen == [
        ("GET", "/api/v3.1/connected_accounts/ca_1"),
        ("DELETE", "/api/v3.1/connected_accounts/ca_1"),
    ]


async def test_an_auth_config_is_found_by_toolkit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {"toolkit_slug": "googlecalendar"}
        return httpx.Response(
            200,
            json={"items": [{"id": "ac_cal", "toolkit": {"slug": "googlecalendar"}}]},
        )

    assert await composio(handler).find_auth_config("googlecalendar") == "ac_cal"


async def test_no_auth_config_means_none() -> None:
    client = composio(lambda request: httpx.Response(200, json={"items": []}))

    assert await client.find_auth_config("notion") is None


async def test_a_managed_auth_config_is_created_for_the_toolkit() -> None:
    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(
            201,
            json={
                "toolkit": {"slug": "gmail"},
                "auth_config": {"id": "ac_new", "is_composio_managed": True},
            },
        )

    assert await composio(handler).create_managed_auth_config("gmail") == "ac_new"
    assert seen == [
        (
            "POST",
            "/api/v3.1/auth_configs",
            {
                "toolkit": {"slug": "gmail"},
                "auth_config": {"type": "use_composio_managed_auth", "credentials": {}},
            },
        )
    ]


async def test_a_created_auth_config_without_an_id_is_an_error() -> None:
    client = composio(lambda request: httpx.Response(201, json={"auth_config": {}}))

    with pytest.raises(IntegrationError, match="without an id"):
        await client.create_managed_auth_config("gmail")


async def test_a_composio_timeout_is_an_integration_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(IntegrationError, match="timed out"):
        await composio(handler).list_active_accounts("user-1")


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "rejected the API key"), (500, "HTTP 500")],
)
async def test_browserbase_failures_do_not_echo_the_provider(status: int, expected: str) -> None:
    client = browserbase(lambda request: httpx.Response(status, json={"error": SECRET_ECHO}))

    with pytest.raises(IntegrationError) as caught:
        await client.get_run("run_1")

    assert expected in caught.value.message
    assert "buy milk" not in caught.value.message


async def test_browserbase_answers_that_are_not_json_are_rejected() -> None:
    client = browserbase(lambda request: httpx.Response(200, text="<html>"))

    with pytest.raises(IntegrationError, match="not JSON"):
        await client.get_run("run_1")


async def test_an_unreachable_browserbase_is_an_integration_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(IntegrationError, match="could not be reached"):
        await browserbase(handler).start_run("task")


async def test_a_live_view_without_an_https_address_is_absent() -> None:
    client = browserbase(lambda request: httpx.Response(200, json={"debuggerUrl": "ws://x"}))

    assert await client.live_view_url("bb_1") is None
