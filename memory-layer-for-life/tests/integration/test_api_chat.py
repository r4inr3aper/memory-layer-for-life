"""The assistant app's chat API, end to end against PostgreSQL with a scripted model."""

import asyncio
import base64
import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import transaction
from app.domain.errors import AssistantBillingError
from app.integrations.assistant.base import AssistantText, Attachment, UserText
from app.models.app_user import AppUser
from app.models.chat_thread import ChatThread
from app.models.scheduled_task_run import ScheduledTaskRun
from tests.integration.conftest import AssistantHarness, AssistantHarnessFactory
from tests.support.app_api import API, confirmed_schedule, main_thread, run_now, stream
from tests.support.assistant import call, new_principal, say

# --- Sign-in ---------------------------------------------------------------------------


async def test_app_routes_need_an_access_token(assistant_api: AssistantHarness) -> None:
    response = await assistant_api.client.get(f"{API}/threads")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error_code"] == "AUTHENTICATION_REQUIRED"


async def test_an_unknown_token_is_refused(assistant_api: AssistantHarness) -> None:
    response = await assistant_api.client.get(
        f"{API}/threads", headers={"Authorization": "Bearer forged"}
    )

    assert response.status_code == 401


async def test_without_supabase_sign_in_is_unavailable(api_without_extractor: AsyncClient) -> None:
    response = await api_without_extractor.get(
        f"{API}/me", headers={"Authorization": "Bearer anything"}
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "AUTHENTICATION_NOT_CONFIGURED"


async def test_the_memory_layer_stays_open_to_the_console(assistant_api: AssistantHarness) -> None:
    assert (await assistant_api.client.get(f"{API}/memories")).status_code == 200


async def test_the_first_request_creates_the_user_and_later_ones_refresh_them(
    assistant_api: AssistantHarness,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    principal = new_principal("Ada")

    first = await assistant_api.client.get(f"{API}/me", headers=assistant_api.sign_in(principal))
    renamed = type(principal)(id=principal.id, email="ada@new.example", display_name="Ada L.")
    second = await assistant_api.client.get(f"{API}/me", headers=assistant_api.sign_in(renamed))

    assert first.status_code == 200
    assert first.json()["email"] == "ada@example.com"
    assert second.json()["email"] == "ada@new.example"
    assert second.json()["display_name"] == "Ada L."
    async with session_factory() as session:
        users = list(await session.scalars(select(AppUser)))
    assert [user.id for user in users] == [principal.id]


# --- Threads ---------------------------------------------------------------------------


async def test_the_main_thread_is_created_once(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())

    first, second = await asyncio.gather(
        assistant_api.client.post(f"{API}/threads/main", headers=headers),
        assistant_api.client.post(f"{API}/threads/main", headers=headers),
    )
    third = await assistant_api.client.post(f"{API}/threads/main", headers=headers)

    assert first.json()["id"] == second.json()["id"] == third.json()["id"]
    assert first.json()["kind"] == "main"
    assert first.json()["title"] == "Main Chat"


async def test_side_threads_are_listed_newest_activity_first(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    await main_thread(assistant_api, headers)
    older = (await assistant_api.client.post(f"{API}/threads", json={}, headers=headers)).json()
    assistant_api.clock.advance(minutes=1)
    newer = (
        await assistant_api.client.post(
            f"{API}/threads", json={"title": "Trip planning"}, headers=headers
        )
    ).json()

    listing = await assistant_api.client.get(f"{API}/threads?kind=side", headers=headers)

    body = listing.json()
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [newer["id"], older["id"]]
    assert newer["title"] == "Trip planning"
    assert older["title"] == "New chat"


async def test_side_threads_can_be_deleted_but_the_main_thread_cannot(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    main_id = await main_thread(assistant_api, headers)
    side = (await assistant_api.client.post(f"{API}/threads", json={}, headers=headers)).json()

    deleted = await assistant_api.client.delete(f"{API}/threads/{side['id']}", headers=headers)
    protected = await assistant_api.client.delete(f"{API}/threads/{main_id}", headers=headers)
    gone = await assistant_api.client.get(f"{API}/threads/{side['id']}", headers=headers)

    assert deleted.status_code == 204
    assert protected.status_code == 409
    assert protected.json()["error_code"] == "PROTECTED_THREAD"
    assert gone.status_code == 404


async def test_another_user_s_thread_reads_as_missing(assistant_api: AssistantHarness) -> None:
    owner = assistant_api.sign_in(new_principal("Owner"))
    stranger = assistant_api.sign_in(new_principal("Stranger"))
    thread_id = await main_thread(assistant_api, owner)

    for response in (
        await assistant_api.client.get(f"{API}/threads/{thread_id}", headers=stranger),
        await assistant_api.client.get(f"{API}/threads/{thread_id}/messages", headers=stranger),
        await assistant_api.client.post(
            f"{API}/threads/{thread_id}/messages", json={"content": "hi"}, headers=stranger
        ),
        await assistant_api.client.delete(f"{API}/threads/{thread_id}", headers=stranger),
    ):
        assert response.status_code == 404


# --- Turns -----------------------------------------------------------------------------


async def test_a_reply_streams_and_both_messages_are_stored(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(say("Hi! How can I help?", "Hi! ", "How can I help?"))

    events = await stream(assistant_api, headers, thread_id, "  hello  ")

    assert [event["type"] for event in events] == [
        "turn_started",
        "text_delta",
        "text_delta",
        "final",
    ]
    assert events[0]["user_message"]["content"] == "hello"
    assert "".join(event["text"] for event in events if event["type"] == "text_delta") == (
        "Hi! How can I help?"
    )
    final = events[-1]["message"]
    assert (final["role"], final["content"]) == ("assistant", "Hi! How can I help?")

    listing = await assistant_api.client.get(f"{API}/threads/{thread_id}/messages", headers=headers)
    stored = listing.json()["items"]
    assert [(item["role"], item["content"]) for item in stored] == [
        ("user", "hello"),
        ("assistant", "Hi! How can I help?"),
    ]
    assert stored[0]["id"] == events[0]["user_message"]["id"]
    assert stored[1]["id"] == final["id"]


async def test_the_model_sees_the_thread_s_history(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(say("Nice to meet you, Ada."), say("Your name is Ada."))

    await stream(assistant_api, headers, thread_id, "I am Ada.")
    await stream(assistant_api, headers, thread_id, "What is my name?")

    transcript = assistant_api.model.requests[1].transcript
    assert transcript == (
        UserText("I am Ada."),
        AssistantText("Nice to meet you, Ada."),
        UserText("What is my name?"),
    )
    context = assistant_api.model.requests[1].request.context
    assert "(UTC)" in context
    assert "Connected apps: none." in context


async def test_a_side_thread_is_titled_by_its_first_message(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    side = (await assistant_api.client.post(f"{API}/threads", json={}, headers=headers)).json()
    assistant_api.model.script(say("Sure."), say("Again."))

    await stream(assistant_api, headers, side["id"], "Plan a weekend in Lisbon for two")
    await stream(assistant_api, headers, side["id"], "Something else entirely")

    thread = await assistant_api.client.get(f"{API}/threads/{side['id']}", headers=headers)
    assert thread.json()["title"] == "Plan a weekend in Lisbon for two"


async def test_a_failed_model_call_is_reported_and_only_the_user_message_stays(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(AssistantBillingError("The Anthropic account has no credit left."))

    events = await stream(assistant_api, headers, thread_id, "hello")

    assert events[-1] == {
        "type": "error",
        "error_code": "ASSISTANT_PROVIDER_BILLING",
        "message": "The Anthropic account has no credit left.",
    }
    listing = await assistant_api.client.get(f"{API}/threads/{thread_id}/messages", headers=headers)
    assert [item["role"] for item in listing.json()["items"]] == ["user"]


async def test_one_turn_runs_per_thread_at_a_time(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.gate = asyncio.Event()
    assistant_api.model.script(say("first"))

    first = asyncio.create_task(stream(assistant_api, headers, thread_id, "one"))
    while not assistant_api.model.requests:
        await asyncio.sleep(0.01)
    second = await assistant_api.client.post(
        f"{API}/threads/{thread_id}/messages", json={"content": "two"}, headers=headers
    )
    assistant_api.model.gate.set()
    events = await first

    assert second.status_code == 409
    assert second.json()["error_code"] == "CHAT_TURN_IN_PROGRESS"
    assert events[-1]["type"] == "final"


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"content": "   "}, 422),
        ({"content": "x" * 8001}, 422),
        ({"content": "hi", "timezone": "Mars/Base"}, 422),
        ({"content": "hi", "extra": 1}, 422),
    ],
)
async def test_invalid_messages_are_refused_before_anything_is_stored(
    assistant_api: AssistantHarness, payload: dict[str, object], status: int
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)

    response = await assistant_api.client.post(
        f"{API}/threads/{thread_id}/messages", json=payload, headers=headers
    )

    assert response.status_code == status
    listing = await assistant_api.client.get(f"{API}/threads/{thread_id}/messages", headers=headers)
    assert listing.json()["total"] == 0


async def test_without_a_model_chat_is_unavailable_and_nothing_is_stored(
    sign_in_only_api: AssistantHarness,
) -> None:
    harness = sign_in_only_api
    headers = harness.sign_in(new_principal())
    thread_id = await main_thread(harness, headers)

    response = await harness.client.post(
        f"{API}/threads/{thread_id}/messages", json={"content": "hi"}, headers=headers
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "PROVIDER_NOT_CONFIGURED"
    listing = await harness.client.get(f"{API}/threads/{thread_id}/messages", headers=headers)
    assert listing.json()["total"] == 0


async def test_the_reply_is_saved_even_when_nobody_reads_the_stream(
    assistant_api: AssistantHarness,
) -> None:
    container = assistant_api.container
    principal = new_principal()
    await container.user_service.ensure(principal)
    thread = await container.chat_service.ensure_main_thread(principal)
    assistant_api.model.script(say("Saved anyway."))

    events = await container.chat_turn_service.start(
        principal, thread.id, "hello", timezone_name="UTC"
    )
    first = await anext(events)
    await events.aclose()  # the client went away
    await container.background.wait()

    messages, total = await container.chat_service.list_messages(
        principal, thread.id, limit=10, offset=0
    )
    assert first.user_message.content == "hello"  # type: ignore[union-attr]
    assert total == 2
    assert messages[-1].content == "Saved anyway."


async def test_messages_page_back_in_time(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    for number in range(3):
        assistant_api.model.script(say(f"reply {number}"))
        assistant_api.clock.advance(seconds=1)
        await stream(assistant_api, headers, thread_id, f"message {number}")

    latest = await assistant_api.client.get(
        f"{API}/threads/{thread_id}/messages?limit=2", headers=headers
    )
    earlier = await assistant_api.client.get(
        f"{API}/threads/{thread_id}/messages?limit=2&offset=2", headers=headers
    )

    assert [item["content"] for item in latest.json()["items"]] == ["message 2", "reply 2"]
    assert [item["content"] for item in earlier.json()["items"]] == ["message 1", "reply 1"]
    assert latest.json()["total"] == 6


# --- Schedule proposals ----------------------------------------------------------------

PROPOSAL = {
    "title": "Morning news",
    "task": "Summarize the three most important AI news stories of the last day.",
    "frequency": "daily",
    "time": "08:00",
    "summary": "Every day at 8:00 I will post the AI news here.",
}


async def propose(harness: AssistantHarness, headers: dict[str, str]) -> tuple[str, dict[str, Any]]:
    thread_id = await main_thread(harness, headers)
    harness.model.script(
        call("propose_schedule", PROPOSAL),
        say("I can post the AI news here every morning at 8. Confirm to start."),
    )
    events = await stream(harness, headers, thread_id, "Send me AI news every morning")
    return thread_id, events[-1]["message"]


async def test_a_proposal_is_shown_and_nothing_is_scheduled_yet(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())

    _, message = await propose(assistant_api, headers)

    proposal = message["metadata"]["schedule_proposal"]
    assert proposal["status"] == "pending"
    assert (proposal["frequency"], proposal["local_time"], proposal["delivery"]) == (
        "daily",
        "08:00",
        "chat",
    )
    assert proposal["original_prompt"] == "Send me AI news every morning"
    schedules = await assistant_api.client.get(f"{API}/schedules", headers=headers)
    assert schedules.json()["total"] == 0


async def test_confirming_creates_exactly_the_proposed_schedule_once(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id, message = await propose(assistant_api, headers)
    path = f"{API}/threads/{thread_id}/messages/{message['id']}/proposal"

    confirmed = await assistant_api.client.post(f"{path}/confirm", headers=headers)
    again = await assistant_api.client.post(f"{path}/confirm", headers=headers)
    dismissed = await assistant_api.client.post(f"{path}/dismiss", headers=headers)

    assert confirmed.status_code == 201, confirmed.text
    body = confirmed.json()
    schedule = body["schedule"]
    assert schedule["task"] == PROPOSAL["task"]
    assert schedule["status"] == "active"
    assert schedule["source_thread_id"] == thread_id
    # The clock starts at 2026-10-01 12:00 UTC, so the next 08:00 UTC is the next day.
    assert schedule["next_run_at"].startswith("2026-10-02T08:00:00")
    proposal = body["message"]["metadata"]["schedule_proposal"]
    assert (proposal["status"], proposal["scheduled_task_id"]) == ("confirmed", schedule["id"])
    assert again.status_code == 409
    assert dismissed.status_code == 409
    listing = await assistant_api.client.get(f"{API}/schedules", headers=headers)
    assert listing.json()["total"] == 1


async def test_a_dismissed_proposal_cannot_be_confirmed(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id, message = await propose(assistant_api, headers)
    path = f"{API}/threads/{thread_id}/messages/{message['id']}/proposal"

    dismissed = await assistant_api.client.post(f"{path}/dismiss", headers=headers)
    confirmed = await assistant_api.client.post(f"{path}/confirm", headers=headers)

    assert dismissed.json()["metadata"]["schedule_proposal"]["status"] == "dismissed"
    assert confirmed.status_code == 409


async def test_a_message_without_a_proposal_cannot_be_confirmed(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(say("hello"))
    events = await stream(assistant_api, headers, thread_id, "hi")

    response = await assistant_api.client.post(
        f"{API}/threads/{thread_id}/messages/{events[-1]['message']['id']}/proposal/confirm",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "SCHEDULE_PROPOSAL_UNAVAILABLE"


# --- Attachments -----------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\nnot really an image"


def attachment(name: str, media_type: str, data: bytes = PNG) -> dict[str, str]:
    return {"name": name, "media_type": media_type, "data": base64.b64encode(data).decode()}


async def test_files_reach_the_model_and_only_a_note_of_them_is_stored(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(say("A cat."), say("Still a cat."))

    events = await stream(
        assistant_api,
        headers,
        thread_id,
        "What is this?",
        attachments=[attachment("cat.png", "image/png")],
    )
    await stream(assistant_api, headers, thread_id, "And now?")

    assert assistant_api.model.requests[0].transcript == (
        UserText("What is this?", attachments=(Attachment("cat.png", "image/png", PNG),)),
    )
    assert events[0]["user_message"]["metadata"]["attachments"] == [
        {"name": "cat.png", "media_type": "image/png", "size_bytes": len(PNG)}
    ]
    # Files are sent once; later turns only learn that they were attached.
    assert assistant_api.model.requests[1].transcript[0] == UserText(
        "What is this?\n\n[Attached earlier: cat.png]"
    )


async def test_files_alone_make_a_message(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(say("A report."))

    events = await stream(
        assistant_api,
        headers,
        thread_id,
        "",
        attachments=[attachment("q3.pdf", "application/pdf"), attachment("cat.png", "image/png")],
    )

    assert events[0]["user_message"]["content"] == "Attached: q3.pdf, cat.png"
    [sent] = assistant_api.model.requests[0].transcript
    assert isinstance(sent, UserText)
    assert [item.name for item in sent.attachments] == ["q3.pdf", "cat.png"]


@pytest.mark.parametrize(
    ("files", "error_code"),
    [
        ([attachment("notes.txt", "text/plain")], "VALIDATION_ERROR"),
        (
            [{"name": "cat.png", "media_type": "image/png", "data": "not base64!"}],
            "VALIDATION_ERROR",
        ),
        ([attachment("empty.png", "image/png", b"")], "INVALID_ATTACHMENT"),
        ([attachment(f"{n}.png", "image/png") for n in range(4)], "INVALID_ATTACHMENT"),
    ],
)
async def test_invalid_files_are_refused_before_anything_is_stored(
    assistant_api: AssistantHarness, files: list[dict[str, str]], error_code: str
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)

    response = await assistant_api.client.post(
        f"{API}/threads/{thread_id}/messages",
        json={"content": "look", "attachments": files},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == error_code
    listing = await assistant_api.client.get(f"{API}/threads/{thread_id}/messages", headers=headers)
    assert listing.json()["total"] == 0


async def test_a_file_over_the_size_limit_is_refused(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    async with assistant_api_with(CHAT_MAX_ATTACHMENT_BYTES=10) as harness:
        headers = harness.sign_in(new_principal())
        thread_id = await main_thread(harness, headers)

        response = await harness.client.post(
            f"{API}/threads/{thread_id}/messages",
            json={"content": "look", "attachments": [attachment("cat.png", "image/png")]},
            headers=headers,
        )

    assert response.status_code == 422
    assert response.json()["message"] == "cat.png is larger than 10 bytes."


# --- Clearing a thread -----------------------------------------------------------------


async def test_clearing_a_thread_keeps_the_thread_and_its_schedule_s_runs(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    assistant_api.model.script(say("Result."))
    run = await run_now(assistant_api, headers, schedule["id"])
    thread_id = await main_thread(assistant_api, headers)

    cleared = await assistant_api.client.delete(
        f"{API}/threads/{thread_id}/messages", headers=headers
    )

    assert cleared.status_code == 204
    listing = await assistant_api.client.get(f"{API}/threads/{thread_id}/messages", headers=headers)
    assert listing.json()["total"] == 0
    assert (await main_thread(assistant_api, headers)) == thread_id
    async with session_factory() as session:
        stored_run = await session.get(ScheduledTaskRun, uuid.UUID(run["id"]))
    assert stored_run is not None
    assert stored_run.chat_message_id is None


async def test_a_thread_cannot_be_cleared_while_a_reply_runs(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.gate = asyncio.Event()
    assistant_api.model.script(say("first"))

    running = asyncio.create_task(stream(assistant_api, headers, thread_id, "one"))
    while not assistant_api.model.requests:
        await asyncio.sleep(0.01)
    refused = await assistant_api.client.delete(
        f"{API}/threads/{thread_id}/messages", headers=headers
    )
    assistant_api.model.gate.set()
    await running

    assert refused.status_code == 409
    assert refused.json()["error_code"] == "CHAT_TURN_IN_PROGRESS"


async def test_another_user_s_thread_cannot_be_cleared(assistant_api: AssistantHarness) -> None:
    owner = assistant_api.sign_in(new_principal("Owner"))
    stranger = assistant_api.sign_in(new_principal("Stranger"))
    thread_id = await main_thread(assistant_api, owner)

    response = await assistant_api.client.delete(
        f"{API}/threads/{thread_id}/messages", headers=stranger
    )

    assert response.status_code == 404


# --- One reply per thread, across processes --------------------------------------------


async def test_a_reply_running_in_another_process_holds_the_thread(
    assistant_api: AssistantHarness, assistant_api_with: AssistantHarnessFactory
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.gate = asyncio.Event()
    assistant_api.model.script(say("first"))

    async with assistant_api_with() as other_process:
        other_headers = other_process.sign_in(principal)
        other_process.model.script(say("second"))
        running = asyncio.create_task(stream(assistant_api, headers, thread_id, "one"))
        while not assistant_api.model.requests:
            await asyncio.sleep(0.01)

        refused = await other_process.client.post(
            f"{API}/threads/{thread_id}/messages", json={"content": "two"}, headers=other_headers
        )
        assistant_api.model.gate.set()
        await running
        # The thread is free as soon as the final event arrives.
        events = await stream(other_process, other_headers, thread_id, "two")

    assert refused.status_code == 409
    assert events[-1]["type"] == "final"


async def test_a_failed_reply_frees_the_thread(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(AssistantBillingError("No credit."), say("Back."))

    failed = await stream(assistant_api, headers, thread_id, "one")
    events = await stream(assistant_api, headers, thread_id, "two")

    assert failed[-1]["type"] == "error"
    assert events[-1]["type"] == "final"


async def test_a_lease_left_by_a_stopped_process_expires(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    async with transaction(session_factory) as session:
        thread = await session.get(ChatThread, uuid.UUID(thread_id))
        assert thread is not None
        thread.turn_lease_until = assistant_api.clock() + timedelta(minutes=10)
    assistant_api.model.script(say("Back."))

    held = await assistant_api.client.post(
        f"{API}/threads/{thread_id}/messages", json={"content": "one"}, headers=headers
    )
    assistant_api.clock.advance(minutes=10, seconds=1)
    events = await stream(assistant_api, headers, thread_id, "two")

    assert held.status_code == 409
    assert events[-1]["type"] == "final"
