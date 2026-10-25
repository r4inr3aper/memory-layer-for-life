"""The Expo push and Supabase admin adapters, against a mock HTTP transport."""

import json
import uuid
from collections.abc import Callable

import httpx
import pytest

from app.domain.errors import IntegrationError
from app.integrations.expo_push import PUSH_URL, ExpoPushClient, PushMessage
from app.integrations.supabase_admin import SupabaseAdminClient

Handler = Callable[[httpx.Request], httpx.Response]
USER_ID = uuid.UUID("6f1c2a43-0d5e-4b8e-9a51-1f0e6a8a2b11")


def http_client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def message(number: int) -> PushMessage:
    return PushMessage(
        token=f"ExponentPushToken[{number}]",
        title="Morning news: done",
        body="Three stories.",
        data={"thread_id": "t1"},
    )


# --- Expo push -------------------------------------------------------------------------


async def test_messages_are_sent_in_batches_of_one_hundred_with_the_access_token() -> None:
    batches: list[list[dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == PUSH_URL
        assert request.headers["authorization"] == "Bearer expo_token"
        body = json.loads(request.content)
        batches.append(body)
        return httpx.Response(200, json={"data": [{"status": "ok"} for _ in body]})

    receipt = await ExpoPushClient(http_client(handler), access_token="expo_token").send(
        [message(number) for number in range(150)]
    )

    assert [len(batch) for batch in batches] == [100, 50]
    assert batches[0][0] == {
        "to": "ExponentPushToken[0]",
        "title": "Morning news: done",
        "body": "Three stories.",
        "data": {"thread_id": "t1"},
        "sound": "default",
    }
    assert (receipt.sent, receipt.unregistered_tokens) == (150, ())


async def test_dead_tokens_are_reported_and_other_errors_are_not() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "data": [
                    {"status": "ok"},
                    {"status": "error", "details": {"error": "DeviceNotRegistered"}},
                    {"status": "error", "details": {"error": "MessageRateExceeded"}},
                ]
            },
        )

    receipt = await ExpoPushClient(http_client(handler), access_token=None).send(
        [message(1), message(2), message(3)]
    )

    assert (receipt.sent, receipt.unregistered_tokens) == (1, ("ExponentPushToken[2]",))


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(500), "rejected the request (HTTP 500)."),
        (httpx.Response(200, content=b"not json"), "answered with an unexpected shape."),
    ],
)
async def test_a_failing_push_service_raises(response: httpx.Response, reason: str) -> None:
    client = ExpoPushClient(http_client(lambda request: response), access_token=None)

    with pytest.raises(IntegrationError) as raised:
        await client.send([message(1)])

    assert raised.value.message == f"Expo push: {reason}"


async def test_an_unreachable_push_service_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(IntegrationError, match="could not be reached"):
        await ExpoPushClient(http_client(handler), access_token=None).send([message(1)])


# --- Supabase admin --------------------------------------------------------------------


def admin(handler: Handler) -> SupabaseAdminClient:
    return SupabaseAdminClient(
        http_client(handler), supabase_url="https://project.supabase.test", secret_key="sb_secret"
    )


async def test_the_identity_is_deleted_with_the_secret_key_as_apikey_only() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    await admin(handler).delete_user(USER_ID)

    [request] = seen
    assert request.method == "DELETE"
    assert str(request.url) == f"https://project.supabase.test/auth/v1/admin/users/{USER_ID}"
    assert request.headers["apikey"] == "sb_secret"
    assert "authorization" not in request.headers


async def test_an_identity_already_gone_counts_as_deleted() -> None:
    await admin(lambda request: httpx.Response(404, json={"msg": "User not found"})).delete_user(
        USER_ID
    )


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "rejected SUPABASE_SECRET_KEY."),
        (403, "rejected SUPABASE_SECRET_KEY."),
        (500, "could not delete the user (HTTP 500)."),
    ],
)
async def test_a_refused_deletion_raises(status: int, reason: str) -> None:
    with pytest.raises(IntegrationError) as raised:
        await admin(lambda request: httpx.Response(status)).delete_user(USER_ID)

    assert raised.value.message == f"Supabase Auth: {reason}"
