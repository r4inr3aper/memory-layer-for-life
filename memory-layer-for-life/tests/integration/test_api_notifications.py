"""Push notifications: device registration, and a notification when a scheduled run ends."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import AssistantModelError, IntegrationError
from app.models.push_token import PushToken
from tests.integration.conftest import AssistantHarness
from tests.support.app_api import API, confirmed_schedule, main_thread, run_now
from tests.support.assistant import new_principal, say

PHONE = "ExponentPushToken[phone]"
TABLET = "ExponentPushToken[tablet]"


async def register(
    harness: AssistantHarness, headers: dict[str, str], token: str, platform: str = "ios"
) -> None:
    response = await harness.client.post(
        f"{API}/me/push-tokens", json={"token": token, "platform": platform}, headers=headers
    )
    assert response.status_code == 204, response.text


async def stored_tokens(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[tuple[str, str, str]]:
    async with session_factory() as session:
        rows = await session.scalars(select(PushToken).order_by(PushToken.token))
        return [(str(row.user_id), row.token, row.platform) for row in rows]


# --- Registration ----------------------------------------------------------------------


async def test_registering_a_device_is_idempotent(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)

    await register(assistant_api, headers, PHONE)
    await register(assistant_api, headers, PHONE)

    assert await stored_tokens(session_factory) == [(str(principal.id), PHONE, "ios")]


async def test_a_device_belongs_to_whoever_signed_in_on_it_last(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    first = new_principal("First")
    second = new_principal("Second")
    await register(assistant_api, assistant_api.sign_in(first), PHONE, "android")

    await register(assistant_api, assistant_api.sign_in(second), PHONE, "android")

    assert await stored_tokens(session_factory) == [(str(second.id), PHONE, "android")]


async def test_unregistering_stops_only_the_user_s_own_device(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    owner = new_principal("Owner")
    stranger = assistant_api.sign_in(new_principal("Stranger"))
    headers = assistant_api.sign_in(owner)
    await register(assistant_api, headers, PHONE)
    await register(assistant_api, headers, TABLET)

    ignored = await assistant_api.client.delete(f"{API}/me/push-tokens/{PHONE}", headers=stranger)
    removed = await assistant_api.client.delete(f"{API}/me/push-tokens/{PHONE}", headers=headers)

    assert (ignored.status_code, removed.status_code) == (204, 204)
    assert await stored_tokens(session_factory) == [(str(owner.id), TABLET, "ios")]


@pytest.mark.parametrize(
    "payload",
    [{"token": "", "platform": "ios"}, {"token": PHONE, "platform": "symbian"}, {"token": PHONE}],
)
async def test_invalid_devices_are_refused(
    assistant_api: AssistantHarness, payload: dict[str, str]
) -> None:
    headers = assistant_api.sign_in(new_principal())

    response = await assistant_api.client.post(
        f"{API}/me/push-tokens", json=payload, headers=headers
    )

    assert response.status_code == 422


# --- Notifications ---------------------------------------------------------------------


async def test_a_finished_run_notifies_every_device_and_leads_to_the_result(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    await register(assistant_api, headers, PHONE)
    await register(assistant_api, headers, TABLET, "android")
    assistant_api.model.script(say("1. Story one.\n2. Story two."))

    run = await run_now(assistant_api, headers, schedule["id"])

    thread_id = await main_thread(assistant_api, headers)
    sent = assistant_api.push.sent
    assert sorted(message.token for message in sent) == [PHONE, TABLET]
    message = sent[0]
    assert message.title == "Morning news: done"
    assert message.body == "1. Story one. 2. Story two."
    assert message.data == {
        "scheduled_task_id": schedule["id"],
        "run_id": run["id"],
        "thread_id": thread_id,
    }


async def test_a_failed_run_says_why(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    await register(assistant_api, headers, PHONE)
    assistant_api.model.script(AssistantModelError("The Anthropic API could not be reached."))

    await run_now(assistant_api, headers, schedule["id"])

    [message] = assistant_api.push.sent
    assert message.title == "Morning news: failed"
    assert message.body == "The Anthropic API could not be reached."


async def test_a_long_result_is_shortened(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    await register(assistant_api, headers, PHONE)
    assistant_api.model.script(say("word " * 100))

    await run_now(assistant_api, headers, schedule["id"])

    [message] = assistant_api.push.sent
    assert len(message.body) == 180
    assert message.body.endswith("…")


async def test_nothing_is_sent_when_notifications_are_off(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    await register(assistant_api, headers, PHONE)
    await assistant_api.client.patch(
        f"{API}/me", json={"notifications_enabled": False}, headers=headers
    )
    assistant_api.model.script(say("Result."))

    run = await run_now(assistant_api, headers, schedule["id"])

    assert run["status"] == "succeeded"
    assert assistant_api.push.sent == []


async def test_a_device_expo_no_longer_knows_is_forgotten(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    schedule = await confirmed_schedule(assistant_api, headers)
    await register(assistant_api, headers, PHONE)
    await register(assistant_api, headers, TABLET)
    assistant_api.push.dead_tokens = {PHONE}
    assistant_api.model.script(say("Result."))

    await run_now(assistant_api, headers, schedule["id"])

    assert await stored_tokens(session_factory) == [(str(principal.id), TABLET, "ios")]


async def test_a_failed_notification_does_not_affect_the_run(
    assistant_api: AssistantHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    await register(assistant_api, headers, PHONE)

    async def unreachable(messages: object) -> None:
        raise IntegrationError("Expo push", "could not be reached.")

    monkeypatch.setattr(assistant_api.push, "send", unreachable)
    assistant_api.model.script(say("Result."))

    run = await run_now(assistant_api, headers, schedule["id"])

    assert run["status"] == "succeeded"
