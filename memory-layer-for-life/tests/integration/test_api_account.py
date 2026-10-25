"""The signed-in user's account: personalization, feedback, and deletion."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.errors import IntegrationError
from app.models.app_user import AppUser
from app.models.chat_thread import ChatThread
from app.models.daily_usage import DailyUsage
from app.models.feedback import Feedback
from app.models.llm_call import LlmCall
from app.models.push_token import PushToken
from app.models.scheduled_task import ScheduledTask
from tests.integration.conftest import AssistantHarness, AssistantHarnessFactory
from tests.support.app_api import API, confirmed_schedule, main_thread, stream
from tests.support.assistant import new_principal, say
from tests.support.pipeline import DEFAULT_START

# --- Personalization -------------------------------------------------------------------


async def test_a_new_user_has_the_default_assistant(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())

    me = (await assistant_api.client.get(f"{API}/me", headers=headers)).json()

    assert (
        me["assistant_name"],
        me["assistant_subtitle"],
        me["assistant_icon"],
        me["assistant_color"],
        me["notifications_enabled"],
    ) == (None, None, None, None, True)


async def test_only_the_fields_sent_change(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())

    first = await assistant_api.client.patch(
        f"{API}/me",
        json={
            "assistant_name": "  Nova  ",
            "assistant_subtitle": "Research buddy",
            "assistant_icon": "sparkles",
            "assistant_color": "#1A2B3C",
        },
        headers=headers,
    )
    second = await assistant_api.client.patch(
        f"{API}/me", json={"notifications_enabled": False}, headers=headers
    )
    stored = (await assistant_api.client.get(f"{API}/me", headers=headers)).json()

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert (
        stored["assistant_name"],
        stored["assistant_subtitle"],
        stored["assistant_icon"],
        stored["assistant_color"],
        stored["notifications_enabled"],
    ) == ("Nova", "Research buddy", "sparkles", "#1A2B3C", False)


async def test_a_blank_or_null_text_field_returns_to_the_default(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    await assistant_api.client.patch(
        f"{API}/me",
        json={"assistant_name": "Nova", "assistant_icon": "star", "assistant_color": "#000000"},
        headers=headers,
    )

    response = await assistant_api.client.patch(
        f"{API}/me",
        json={"assistant_name": "   ", "assistant_icon": "", "assistant_color": None},
        headers=headers,
    )

    body = response.json()
    assert (body["assistant_name"], body["assistant_icon"], body["assistant_color"]) == (
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"assistant_name": "x" * 41},
        {"assistant_subtitle": "x" * 61},
        {"assistant_icon": "not a key!"},
        {"assistant_color": "blue"},
        {"assistant_color": "#12345"},
        {"notifications_enabled": None},
        {"email": "someone@else.example"},
    ],
)
async def test_invalid_profile_changes_are_refused(
    assistant_api: AssistantHarness, payload: dict[str, object]
) -> None:
    headers = assistant_api.sign_in(new_principal())

    response = await assistant_api.client.patch(f"{API}/me", json=payload, headers=headers)

    assert response.status_code == 422


async def test_the_assistant_knows_the_name_the_user_gave_it(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(say("Hi."), say("Hi again."))

    await stream(assistant_api, headers, thread_id, "hello")
    await assistant_api.client.patch(f"{API}/me", json={"assistant_name": "Nova"}, headers=headers)
    await stream(assistant_api, headers, thread_id, "hello again")

    first, second = (request.request.context for request in assistant_api.model.requests)
    assert "Your name: Cooper." in first
    assert "Your name: Nova." in second


# --- Feedback --------------------------------------------------------------------------


async def test_feedback_is_stored_for_the_team(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)

    response = await assistant_api.client.post(
        f"{API}/feedback",
        json={
            "message": "  Love it, but dark mode please.  ",
            "platform": "ios",
            "app_version": "1.0.0",
        },
        headers=headers,
    )

    assert response.status_code == 201, response.text
    async with session_factory() as session:
        stored = await session.get(Feedback, response.json()["id"])
    assert stored is not None
    assert (stored.user_id, stored.message, stored.platform, stored.app_version) == (
        principal.id,
        "Love it, but dark mode please.",
        "ios",
        "1.0.0",
    )


@pytest.mark.parametrize(
    "payload",
    [{"message": "   "}, {"message": "x" * 4001}, {"message": "hi", "platform": "symbian"}],
)
async def test_invalid_feedback_is_refused(
    assistant_api: AssistantHarness, payload: dict[str, object]
) -> None:
    headers = assistant_api.sign_in(new_principal())

    response = await assistant_api.client.post(f"{API}/feedback", json=payload, headers=headers)

    assert response.status_code == 422


# --- Deletion --------------------------------------------------------------------------


async def _count(
    session_factory: async_sessionmaker[AsyncSession], model: type[object], user_id: object
) -> int:
    async with session_factory() as session:
        total = await session.scalar(
            select(func.count()).select_from(model).where(model.user_id == user_id)  # type: ignore[attr-defined]
        )
    return int(total or 0)


async def test_deleting_the_account_removes_everything_and_revokes_access(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    await confirmed_schedule(assistant_api, headers)  # a thread, messages, and a schedule
    await assistant_api.client.post(
        f"{API}/me/push-tokens",
        json={"token": "ExponentPushToken[device]", "platform": "android"},
        headers=headers,
    )
    await assistant_api.client.post(f"{API}/feedback", json={"message": "bye"}, headers=headers)
    account = assistant_api.composio.add_account(principal.id, "gmail")
    call_id = new_uuid()
    async with transaction(session_factory) as session:
        session.add(
            LlmCall(
                id=call_id,
                provider="anthropic",
                operation="chat",
                origin="assistant",
                status="succeeded",
                requested_model="claude-haiku-5-5",
                started_at=DEFAULT_START,
                duration_ms=10,
                user_id=principal.id,
            )
        )

    response = await assistant_api.client.delete(f"{API}/me", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "apps_disconnected": 1,
        "apps_not_disconnected": 0,
        "identity_deleted": True,
    }
    assert assistant_api.composio.deleted == [account.id]
    assert assistant_api.identity.deleted == [principal.id]
    for model in (ChatThread, ScheduledTask, PushToken, Feedback, DailyUsage):
        assert await _count(session_factory, model, principal.id) == 0, model.__name__
    async with session_factory() as session:
        assert await session.get(AppUser, principal.id) is None
        call = await session.get(LlmCall, call_id)
    assert call is not None
    assert call.user_id is None  # the cost log keeps its facts without the owner


async def test_signing_in_after_deletion_starts_an_empty_account(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    await assistant_api.client.patch(f"{API}/me", json={"assistant_name": "Nova"}, headers=headers)
    await main_thread(assistant_api, headers)

    await assistant_api.client.delete(f"{API}/me", headers=headers)
    me = await assistant_api.client.get(f"{API}/me", headers=headers)
    threads = await assistant_api.client.get(f"{API}/threads", headers=headers)

    assert me.status_code == 200, me.text
    assert me.json()["assistant_name"] is None
    assert threads.json()["total"] == 0


async def test_an_app_that_cannot_be_revoked_is_reported(
    assistant_api: AssistantHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    assistant_api.composio.add_account(principal.id, "gmail")
    assistant_api.composio.add_account(principal.id, "slack")

    async def refuse(account_id: str) -> None:
        raise IntegrationError("Composio", "could not be reached.")

    monkeypatch.setattr(assistant_api.composio, "delete_account", refuse)

    response = await assistant_api.client.delete(f"{API}/me", headers=headers)

    assert response.status_code == 200
    assert (response.json()["apps_disconnected"], response.json()["apps_not_disconnected"]) == (
        0,
        2,
    )


async def test_without_the_secret_key_the_data_goes_but_the_sign_in_stays(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    async with assistant_api_with(with_identity=False) as harness:
        headers = harness.sign_in(new_principal())
        await main_thread(harness, headers)

        response = await harness.client.delete(f"{API}/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["identity_deleted"] is False
    assert harness.identity.deleted == []


async def test_a_supabase_failure_is_reported_after_the_data_is_gone(
    assistant_api: AssistantHarness,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    await main_thread(assistant_api, headers)

    async def refuse(user_id: object) -> None:
        raise IntegrationError("Supabase Auth", "rejected SUPABASE_SECRET_KEY.")

    monkeypatch.setattr(assistant_api.identity, "delete_user", refuse)

    response = await assistant_api.client.delete(f"{API}/me", headers=headers)

    assert response.status_code == 502
    assert response.json()["error_code"] == "INTEGRATION_FAILED"
    assert await _count(session_factory, ChatThread, principal.id) == 0
