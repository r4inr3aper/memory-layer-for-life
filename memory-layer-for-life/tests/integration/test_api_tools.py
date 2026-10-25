"""App connections through Composio, and the assistant's use of them, against PostgreSQL."""

import asyncio

from httpx import Response

from tests.integration.conftest import AssistantHarness, AssistantHarnessFactory
from tests.support.app_api import API, main_thread, stream
from tests.support.assistant import call, new_principal, say


async def test_the_catalog_lists_every_app_as_not_connected_at_first(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())

    response = await assistant_api.client.get(f"{API}/tools", headers=headers)

    tools = {tool["slug"]: tool for tool in response.json()}
    assert {"gmail", "slack", "googlecalendar", "notion"} <= set(tools)
    gmail = tools["gmail"]
    assert gmail["status"] == "not_connected"
    assert gmail["logo_url"] == "https://logos.composio.dev/api/gmail"
    assert gmail["actions"][0]["name"] == "Read email"


async def test_connecting_starts_a_composio_link_with_the_app_callback(
    assistant_api: AssistantHarness,
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)

    response = await assistant_api.client.post(
        f"{API}/tools/gmail/connect", json={"callback_url": "memory://tools"}, headers=headers
    )

    body = response.json()
    assert response.status_code == 200, body
    assert body["connect_url"].startswith("https://connect.composio.dev/link/")
    assert body["tool"]["status"] == "pending"
    created = assistant_api.composio.auth_configs["gmail"]
    assert assistant_api.composio.links == [(str(principal.id), created, "memory://tools")]


async def test_an_app_already_connected_in_composio_is_recognized(
    assistant_api: AssistantHarness,
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    assistant_api.composio.add_account(principal.id, "slack", label="Acme workspace")

    response = await assistant_api.client.post(
        f"{API}/tools/slack/connect", json={}, headers=headers
    )

    body = response.json()
    assert body["connect_url"] is None
    assert (body["tool"]["status"], body["tool"]["connected_label"]) == (
        "connected",
        "Acme workspace",
    )
    assert body["tool"]["connected_at"] is not None
    assert assistant_api.composio.links == []


async def test_checking_after_authorizing_marks_the_app_connected(
    assistant_api: AssistantHarness,
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    await assistant_api.client.post(f"{API}/tools/gmail/connect", json={}, headers=headers)
    assistant_api.composio.add_account(principal.id, "gmail", email="ada@gmail.example")

    response = await assistant_api.client.get(f"{API}/tools/gmail/connection", headers=headers)
    listing = await assistant_api.client.get(f"{API}/tools", headers=headers)

    assert response.json()["status"] == "connected"
    assert response.json()["connected_email"] == "ada@gmail.example"
    gmail = next(tool for tool in listing.json() if tool["slug"] == "gmail")
    assert gmail["status"] == "connected"


async def test_an_abandoned_connect_flow_reads_as_revoked(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    await assistant_api.client.post(f"{API}/tools/gmail/connect", json={}, headers=headers)

    response = await assistant_api.client.get(f"{API}/tools/gmail/connection", headers=headers)

    assert response.json()["status"] == "revoked"


async def test_checking_an_app_never_connected_writes_nothing(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())

    response = await assistant_api.client.get(f"{API}/tools/notion/connection", headers=headers)

    assert response.json()["status"] == "not_connected"
    assert response.json()["last_checked_at"] is None


async def test_disconnecting_removes_every_account_of_the_app(
    assistant_api: AssistantHarness,
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    first = assistant_api.composio.add_account(principal.id, "slack")
    second = assistant_api.composio.add_account(principal.id, "slack")
    other = assistant_api.composio.add_account(principal.id, "gmail")
    await assistant_api.client.get(f"{API}/tools/slack/connection", headers=headers)

    response = await assistant_api.client.delete(f"{API}/tools/slack/connection", headers=headers)

    assert response.json()["status"] == "revoked"
    assert sorted(assistant_api.composio.deleted) == sorted([first.id, second.id])
    assert other.id in assistant_api.composio.accounts


async def connect(harness: AssistantHarness, headers: dict[str, str], slug: str) -> Response:
    return await harness.client.post(f"{API}/tools/{slug}/connect", json={}, headers=headers)


async def test_the_project_s_own_auth_config_is_used(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    assistant_api.composio.auth_configs["googlecalendar"] = "ac_calendar"

    response = await connect(assistant_api, headers, "googlecalendar")

    assert response.status_code == 200, response.text
    assert assistant_api.composio.links[-1][1] == "ac_calendar"
    assert assistant_api.composio.created_auth_configs == []


async def test_without_one_a_managed_auth_config_is_created_once_and_remembered(
    assistant_api: AssistantHarness,
) -> None:
    first = assistant_api.sign_in(new_principal("First"))
    second = assistant_api.sign_in(new_principal("Second"))

    together = await asyncio.gather(
        connect(assistant_api, first, "gmail"), connect(assistant_api, second, "gmail")
    )
    later = await connect(assistant_api, first, "gmail")

    assert [response.status_code for response in [*together, later]] == [200, 200, 200]
    # Concurrent first connects create one auth config, and it is looked up only once.
    assert assistant_api.composio.created_auth_configs == ["gmail"]
    assert assistant_api.composio.auth_config_lookups == ["gmail"]
    created = assistant_api.composio.auth_configs["gmail"]
    assert {link[1] for link in assistant_api.composio.links} == {created}


async def test_an_app_composio_cannot_set_up_is_refused_with_a_reason(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    assistant_api.composio.managed_auth_refused.add("notion")

    response = await connect(assistant_api, headers, "notion")

    assert response.status_code == 502
    assert "could not set up sign-in for Notion (HTTP 400)" in response.json()["message"]
    assert assistant_api.composio.links == []


async def test_an_auth_config_deleted_in_composio_is_replaced(
    assistant_api: AssistantHarness,
) -> None:
    first = assistant_api.sign_in(new_principal("First"))
    second = assistant_api.sign_in(new_principal("Second"))
    await connect(assistant_api, first, "gmail")
    deleted = assistant_api.composio.auth_configs["gmail"]
    assistant_api.composio.remove_auth_config("gmail")

    response = await connect(assistant_api, second, "gmail")

    assert response.status_code == 200, response.text
    replacement = assistant_api.composio.auth_configs["gmail"]
    assert replacement != deleted
    assert assistant_api.composio.links[-1][1] == replacement
    assert assistant_api.composio.created_auth_configs == ["gmail", "gmail"]


async def test_the_operator_s_auth_config_wins_and_a_wrong_one_is_named(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    async with assistant_api_with(COMPOSIO_AUTH_CONFIGS={"gmail": "ac_mine"}) as harness:
        headers = harness.sign_in(new_principal())
        used = await connect(harness, headers, "gmail")
        harness.composio.removed_auth_configs.add("ac_mine")
        missing = await connect(harness, headers, "gmail")

    assert used.status_code == 200, used.text
    assert harness.composio.links[0][1] == "ac_mine"
    assert (harness.composio.auth_config_lookups, harness.composio.created_auth_configs) == (
        [],
        [],
    )
    assert missing.status_code == 502
    assert "has no auth config ac_mine, set for Gmail" in missing.json()["message"]


async def test_unknown_apps_and_unsafe_callbacks_are_refused(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())

    unknown = await assistant_api.client.post(
        f"{API}/tools/myspace/connect", json={}, headers=headers
    )
    unsafe = await assistant_api.client.post(
        f"{API}/tools/gmail/connect",
        json={"callback_url": "javascript:alert(1)"},
        headers=headers,
    )

    assert unknown.status_code == 404
    assert unsafe.status_code == 422


async def test_without_composio_the_catalog_lists_but_connecting_is_unavailable(
    sign_in_only_api: AssistantHarness,
) -> None:
    headers = sign_in_only_api.sign_in(new_principal())

    listing = await sign_in_only_api.client.get(f"{API}/tools", headers=headers)
    connect = await sign_in_only_api.client.post(
        f"{API}/tools/gmail/connect", json={}, headers=headers
    )

    assert listing.status_code == 200
    assert connect.status_code == 503
    assert connect.json()["error_code"] == "INTEGRATION_NOT_CONFIGURED"


async def test_the_assistant_shows_a_connect_button_for_a_missing_app(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(
        call("find_app_tools", {"app": "gmail", "use_case": "read my latest email"}),
        call("connect_app", {"app": "gmail"}),
        say("Connect Gmail with the button below, then tell me when you are done."),
    )

    events = await stream(assistant_api, headers, thread_id, "What's my latest email?")

    types = [event["type"] for event in events]
    assert types.count("tool_started") == 2
    assert "connect_link" in types
    link = events[-1]["message"]["metadata"]["connect_link"]
    assert (link["toolkit"], link["tool_name"]) == ("gmail", "Gmail")
    assert link["connect_url"].startswith("https://connect.composio.dev/link/")


async def test_the_assistant_knows_which_apps_are_connected(
    assistant_api: AssistantHarness,
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    assistant_api.composio.add_account(principal.id, "gmail")
    await assistant_api.client.get(f"{API}/tools/gmail/connection", headers=headers)
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(say("You have Gmail connected."))

    await stream(assistant_api, headers, thread_id, "Which apps can you use?")

    assert "Connected apps: Gmail." in assistant_api.model.requests[-1].request.context
