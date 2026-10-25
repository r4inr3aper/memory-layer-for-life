"""Life state, reminders, the daily brief, searching chats, and Cooper's list tools,
against PostgreSQL. The clock starts on Thursday 1 October 2026 at 12:00 UTC, which is
17:30 in Kolkata, the user's timezone."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.domain.enums import MemoryState, MemoryType, Sensitivity
from app.domain.principal import Principal
from app.integrations.assistant.base import ToolResults
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.models.memory import Memory
from app.schemas.extraction import ExtractionOutput
from app.services.proactive import PRIVATE_REMINDER
from tests.integration.conftest import AssistantHarness
from tests.support.app_api import API, main_thread, stream
from tests.support.assistant import call, say
from tests.support.extraction import evidence, extraction, memory, temporal
from tests.support.memories_api import (
    MEMORIES,
    get_json,
    patch_json,
    post_json,
    remembered,
    sign_up,
)

LIFE = f"{API}/me/life"
TODAY = date(2026, 10, 1)


def task(
    content: str,
    due: date | None = None,
    *,
    memory_type: MemoryType = MemoryType.TASK,
    state: MemoryState = MemoryState.OPEN,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
) -> ExtractionOutput:
    return extraction(
        memory(
            content,
            memory_type=memory_type,
            state=state,
            evidence_refs=[evidence(0, "x")],
            temporal=temporal("then", due) if due is not None else None,
            sensitivity=sensitivity,
        )
    )


async def user_in_kolkata(
    harness: AssistantHarness, **preferences: Any
) -> tuple[Principal, dict[str, str]]:
    principal, headers = await sign_up(harness)
    await patch_json(harness, f"{API}/me", headers, {"timezone": "Asia/Kolkata", **preferences})
    return principal, headers


async def with_push(harness: AssistantHarness, headers: dict[str, str]) -> None:
    await post_json(
        harness,
        f"{API}/me/push-tokens",
        headers,
        {"token": "ExponentPushToken[phone]", "platform": "android"},
        status=204,
    )


async def chat_messages(harness: AssistantHarness, principal: Principal) -> list[ChatMessage]:
    async with harness.container.session_factory() as session:
        rows = await session.scalars(
            select(ChatMessage)
            .join(ChatThread, ChatThread.id == ChatMessage.thread_id)
            .where(ChatThread.user_id == principal.id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
        return list(rows)


def contents(items: list[dict[str, Any]]) -> list[str]:
    return [item["content"] for item in items]


# --- The overview ----------------------------------------------------------------------


async def test_open_items_are_grouped_by_when_they_are_due(assistant_api: AssistantHarness) -> None:
    principal, headers = await user_in_kolkata(assistant_api)
    for message, output in [
        ("renew the passport", task("Renew passport", date(2026, 9, 28))),
        ("pay electricity today", task("Pay the electricity bill", TODAY)),
        ("dentist on saturday", task("Dentist", date(2026, 10, 3), memory_type=MemoryType.PLAN)),
        ("tax filing later on", task("File taxes", date(2026, 10, 20))),
        ("learn the guitar someday", task("Learn guitar", memory_type=MemoryType.INTENTION)),
        ("run a marathon", task("Run a marathon", memory_type=MemoryType.GOAL)),
        ("paid the rent already", task("Paid the rent", TODAY, state=MemoryState.DONE)),
        ("priya lives in pune", task("Priya lives in Pune.", memory_type=MemoryType.SEMANTIC_FACT)),
    ]:
        await remembered(assistant_api, principal, message, output)

    life = await get_json(assistant_api, LIFE, headers)

    assert (life["today"], life["timezone"]) == ("2026-10-01", "Asia/Kolkata")
    assert contents(life["overdue"]) == ["Renew passport"]
    assert contents(life["due_today"]) == ["Pay the electricity bill"]
    assert contents(life["upcoming"]) == ["Dentist"]
    assert contents(life["later"]) == ["File taxes"]
    assert contents(life["someday"]) == ["Learn guitar"]
    assert contents(life["goals"]) == ["Run a marathon"]
    assert life["due_today"][0]["due_on"] == "2026-10-01"
    assert life["due_today"][0]["state"] == "open"


async def test_items_can_be_done_dropped_and_reopened(assistant_api: AssistantHarness) -> None:
    principal, headers = await user_in_kolkata(assistant_api)
    bill = await remembered(assistant_api, principal, "pay the bill", task("Pay bill", TODAY))
    gym = await remembered(assistant_api, principal, "join a gym", task("Join a gym"))

    done = await post_json(assistant_api, f"{MEMORIES}/{bill}/complete", headers)
    dropped = await post_json(assistant_api, f"{MEMORIES}/{gym}/drop", headers)

    assert (done["close_reason"], done["state"], done["status"]) == ("done", "done", "active")
    assert dropped["close_reason"] == "dropped"
    life = await get_json(assistant_api, LIFE, headers)
    assert life["due_today"] == life["someday"] == []
    assert contents(life["recently_done"]) == ["Pay bill"]

    reopened = await post_json(assistant_api, f"{MEMORIES}/{bill}/reopen", headers)

    assert (reopened["closed_at"], reopened["state"]) == (None, "open")
    assert contents((await get_json(assistant_api, LIFE, headers))["due_today"]) == ["Pay bill"]
    detail = await get_json(assistant_api, f"{MEMORIES}/{bill}", headers)
    assert [event["action"] for event in detail["history"]] == ["completed", "reopened"]

    await post_json(assistant_api, f"{MEMORIES}/{gym}/retract", headers)
    refused = await assistant_api.client.post(f"{MEMORIES}/{gym}/complete", headers=headers)
    assert refused.status_code == 409


async def test_a_due_date_and_a_reminder_can_be_set_and_cleared(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await user_in_kolkata(assistant_api)
    item = await remembered(assistant_api, principal, "call the bank", task("Call the bank"))
    later = (assistant_api.clock() + timedelta(hours=2)).isoformat()

    moved = await patch_json(
        assistant_api, f"{MEMORIES}/{item}", headers, {"due_on": "2026-10-02", "remind_at": later}
    )

    assert moved["due_on"] == "2026-10-02"
    assert moved["remind_at"] is not None
    life = await get_json(assistant_api, LIFE, headers)
    assert contents(life["upcoming"]) == contents(life["reminders"]) == ["Call the bank"]
    [event] = (await get_json(assistant_api, f"{MEMORIES}/{item}", headers))["history"]
    assert event["action"] == "scheduled"

    for body in (
        {"remind_at": (assistant_api.clock() - timedelta(minutes=1)).isoformat()},
        {"remind_at": "2026-10-05T10:00:00"},
    ):
        response = await assistant_api.client.patch(
            f"{MEMORIES}/{item}", json=body, headers=headers
        )
        assert response.status_code == 422, body

    cleared = await patch_json(
        assistant_api, f"{MEMORIES}/{item}", headers, {"due_on": None, "remind_at": None}
    )
    assert (cleared["due_on"], cleared["remind_at"]) == (None, None)


# --- Reminders -------------------------------------------------------------------------


async def test_a_due_reminder_is_posted_to_chat_and_pushed_once(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await user_in_kolkata(assistant_api)
    await with_push(assistant_api, headers)
    item = await remembered(assistant_api, principal, "call mum", task("Call Mum"))
    remind_at = assistant_api.clock() + timedelta(minutes=10)
    await patch_json(
        assistant_api, f"{MEMORIES}/{item}", headers, {"remind_at": remind_at.isoformat()}
    )
    dispatcher = assistant_api.container.proactive_dispatcher

    assert await dispatcher.send_due_reminders() == 0
    assistant_api.clock.advance(minutes=11)
    assert await dispatcher.send_due_reminders() == 1
    assert await dispatcher.send_due_reminders() == 0

    [message] = await chat_messages(assistant_api, principal)
    assert message.content == "Reminder: Call Mum"
    assert message.metadata_["reminder"] == {"memory_id": item, "sensitive": False}
    [push] = assistant_api.push.sent
    assert (push.title, push.body, push.data["memory_id"]) == ("Reminder", "Call Mum", item)
    detail = await get_json(assistant_api, f"{MEMORIES}/{item}", headers)
    assert detail["remind_at"] is None
    assert detail["history"][-1]["action"] == "reminded"


async def test_a_sensitive_reminder_keeps_its_text_out_of_chat(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await user_in_kolkata(assistant_api)
    await with_push(assistant_api, headers)
    item = await remembered(
        assistant_api,
        principal,
        "therapy at five",
        task("Therapy session", sensitivity=Sensitivity.SENSITIVE),
    )
    soon = (assistant_api.clock() + timedelta(minutes=1)).isoformat()
    await patch_json(assistant_api, f"{MEMORIES}/{item}", headers, {"remind_at": soon})
    assistant_api.clock.advance(minutes=2)

    await assistant_api.container.proactive_dispatcher.send_due_reminders()

    [message] = await chat_messages(assistant_api, principal)
    assert message.content == f"Reminder: {PRIVATE_REMINDER}"
    assert "Therapy" not in message.content
    assert assistant_api.push.sent[0].body == "A private reminder"


async def test_reminder_pushes_follow_the_user_s_switch(assistant_api: AssistantHarness) -> None:
    principal, headers = await user_in_kolkata(assistant_api, reminders_enabled=False)
    await with_push(assistant_api, headers)
    item = await remembered(assistant_api, principal, "water the plants", task("Water plants"))
    soon = (assistant_api.clock() + timedelta(minutes=1)).isoformat()
    await patch_json(assistant_api, f"{MEMORIES}/{item}", headers, {"remind_at": soon})
    assistant_api.clock.advance(minutes=2)

    await assistant_api.container.proactive_dispatcher.send_due_reminders()

    assert len(await chat_messages(assistant_api, principal)) == 1
    assert assistant_api.push.sent == []


# --- The daily brief -------------------------------------------------------------------


async def test_the_daily_brief_goes_once_at_the_user_s_time(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await user_in_kolkata(
        assistant_api, brief_enabled=True, brief_time="18:00"
    )
    await with_push(assistant_api, headers)
    await remembered(assistant_api, principal, "pay electricity", task("Pay electricity", TODAY))
    invoice = await remembered(
        assistant_api, principal, "send the invoice", task("Send invoice", date(2026, 9, 30))
    )
    dispatcher = assistant_api.container.proactive_dispatcher

    assert await dispatcher.send_due_briefs() == 0  # 17:30 in Kolkata
    assistant_api.clock.advance(minutes=40)
    assert await dispatcher.send_due_briefs() == 1
    assert await dispatcher.send_due_briefs() == 0

    [message] = await chat_messages(assistant_api, principal)
    assert "**Due today**\n- Pay electricity" in message.content
    assert "**Did these get done?**\n- Send invoice" in message.content
    assert message.metadata_["brief"] == {
        "day": "2026-10-01",
        "follow_ups": [{"memory_id": invoice, "content": "Send invoice"}],
    }
    [push] = assistant_api.push.sent
    assert (push.title, push.body) == ("Your day", "1 due today · 1 to check off")
    me = await get_json(assistant_api, f"{API}/me", headers)
    assert (me["brief_enabled"], me["brief_time"]) == (True, "18:00")


async def test_quiet_hours_silence_the_brief_push_but_not_the_message(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await user_in_kolkata(
        assistant_api,
        brief_enabled=True,
        brief_time="17:00",
        quiet_hours_start="17:00",
        quiet_hours_end="19:00",
    )
    await with_push(assistant_api, headers)
    await remembered(assistant_api, principal, "pay electricity", task("Pay electricity", TODAY))

    assert await assistant_api.container.proactive_dispatcher.send_due_briefs() == 1

    assert len(await chat_messages(assistant_api, principal)) == 1
    assert assistant_api.push.sent == []


async def test_a_brief_found_hours_late_or_with_nothing_to_say_is_skipped(
    assistant_api: AssistantHarness,
) -> None:
    late, _ = await user_in_kolkata(assistant_api, brief_enabled=True, brief_time="08:00")
    await remembered(assistant_api, late, "pay electricity", task("Pay electricity", TODAY))
    _, quiet_headers = await sign_up(assistant_api, "Eve")
    await patch_json(
        assistant_api,
        f"{API}/me",
        quiet_headers,
        {"timezone": "Asia/Kolkata", "brief_enabled": True, "brief_time": "17:00"},
    )

    assert await assistant_api.container.proactive_dispatcher.send_due_briefs() == 0
    assert await chat_messages(assistant_api, late) == []


async def test_the_brief_preview_never_lists_sensitive_items(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await user_in_kolkata(assistant_api)
    await remembered(assistant_api, principal, "buy milk today", task("Buy milk", TODAY))
    await remembered(
        assistant_api,
        principal,
        "see the psychiatrist",
        task("See psychiatrist", TODAY, sensitivity=Sensitivity.SENSITIVE),
    )

    brief = await get_json(assistant_api, f"{LIFE}/brief", headers)
    life = await get_json(assistant_api, LIFE, headers)

    assert "Buy milk" in brief["text"]
    assert "psychiatrist" not in brief["text"]
    assert brief["summary"] == "1 due today"
    assert sorted(contents(life["due_today"])) == ["Buy milk", "See psychiatrist"]


async def test_preferences_are_checked(assistant_api: AssistantHarness) -> None:
    _, headers = await sign_up(assistant_api)
    for body in (
        {"brief_time": "25:00"},
        {"brief_time": None},
        {"timezone": "Mars/Olympus"},
        {"quiet_hours_start": "22:00"},
        {"quiet_hours_start": "22:00", "quiet_hours_end": None},
    ):
        response = await assistant_api.client.patch(f"{API}/me", json=body, headers=headers)
        assert response.status_code == 422, body

    me = await patch_json(
        assistant_api,
        f"{API}/me",
        headers,
        {"quiet_hours_start": "22:00", "quiet_hours_end": "07:00"},
    )
    assert (me["quiet_hours_start"], me["quiet_hours_end"]) == ("22:00", "07:00")
    cleared = await patch_json(
        assistant_api, f"{API}/me", headers, {"quiet_hours_start": None, "quiet_hours_end": None}
    )
    assert cleared["quiet_hours_start"] is None


# --- Searching chats -------------------------------------------------------------------


async def test_my_chats_can_be_searched(assistant_api: AssistantHarness) -> None:
    _, headers = await sign_up(assistant_api)
    thread = await main_thread(assistant_api, headers)
    assistant_api.model.script(say("I'll keep the electricity bills in mind."))
    await stream(assistant_api, headers, thread, "The electricity bill was 2400 this month")
    _, stranger = await sign_up(assistant_api, "Eve")
    other = await main_thread(assistant_api, stranger)
    assistant_api.model.script(say("Okay."))
    await stream(assistant_api, stranger, other, "My electricity provider changed")

    found = await post_json(
        assistant_api, f"{API}/me/messages/search", headers, {"query": "electricity"}
    )
    nothing = await post_json(
        assistant_api, f"{API}/me/messages/search", headers, {"query": "what is the"}
    )

    assert sorted(hit["role"] for hit in found["items"]) == ["assistant", "user"]
    assert all(hit["thread_id"] == thread for hit in found["items"])
    user_hit = next(hit for hit in found["items"] if hit["role"] == "user")
    assert "<<electricity>>" in user_hit["snippet"]
    assert user_hit["thread_title"] == "Main Chat"
    assert nothing["items"] == []


# --- Cooper ----------------------------------------------------------------------------


async def test_cooper_sets_a_reminder_and_checks_an_item_off(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await user_in_kolkata(assistant_api)
    thread = await main_thread(assistant_api, headers)
    assistant_api.model.script(
        call("create_reminder", {"text": "Call Mum", "date": "2026-10-02", "time": "18:00"}),
        say("I'll remind you tomorrow at 18:00."),
    )

    await stream(
        assistant_api,
        headers,
        thread,
        "Remind me to call mum tomorrow at 6pm",
        timezone="Asia/Kolkata",
    )

    async with assistant_api.container.session_factory() as session:
        [saved] = await session.scalars(select(Memory).where(Memory.owner_id == principal.id))
    assert (saved.content, saved.created_by, saved.memory_type) == ("Call Mum", "assistant", "task")
    assert saved.remind_at == datetime(2026, 10, 2, 12, 30, tzinfo=UTC)
    assert saved.due_on == date(2026, 10, 2)
    [result] = _tool_results(assistant_api, 1)
    assert "Fri 2 Oct at 18:00" in result

    assistant_api.model.script(
        call("list_open_items"),
        call("update_open_item", {"item_id": str(saved.id), "action": "done"}),
        say("Marked it done."),
    )
    await stream(assistant_api, headers, thread, "I called mum already", timezone="Asia/Kolkata")

    listed = _tool_results(assistant_api, 3)[0]
    assert f"Call Mum (due Fri 02 Oct) [id {saved.id}]" in listed
    item = await get_json(assistant_api, f"{MEMORIES}/{saved.id}", headers)
    assert (item["close_reason"], item["remind_at"]) == ("done", None)


async def test_cooper_never_sees_sensitive_items_on_the_list(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await user_in_kolkata(assistant_api)
    await remembered(assistant_api, principal, "buy milk", task("Buy milk", TODAY))
    await remembered(
        assistant_api,
        principal,
        "rehab appointment",
        task("Rehab appointment", TODAY, sensitivity=Sensitivity.SENSITIVE),
    )
    thread = await main_thread(assistant_api, headers)
    assistant_api.model.script(call("list_open_items"), say("You need to buy milk."))

    await stream(assistant_api, headers, thread, "What's due today?", timezone="Asia/Kolkata")

    [listed] = _tool_results(assistant_api, 1)
    assert "Buy milk" in listed
    assert "Rehab" not in listed


def _tool_results(harness: AssistantHarness, request_index: int) -> list[str]:
    """The tool results the model was given in one of its requests."""
    transcript = harness.model.requests[request_index].transcript
    [results] = [item for item in transcript if isinstance(item, ToolResults)][-1:]
    return [result.content for result in results.results]


async def test_a_to_do_written_by_hand_is_open_with_its_dates(
    assistant_api: AssistantHarness,
) -> None:
    _, headers = await user_in_kolkata(assistant_api)
    remind_at = (assistant_api.clock() + timedelta(hours=1)).isoformat()

    created = await post_json(
        assistant_api,
        MEMORIES,
        headers,
        {
            "memory_type": "task",
            "content": "Book flights",
            "due_on": "2026-10-03",
            "remind_at": remind_at,
        },
        status=201,
    )
    note = await post_json(assistant_api, MEMORIES, headers, {"content": "Likes jazz"}, status=201)

    assert (created["state"], created["due_on"]) == ("open", "2026-10-03")
    assert note["state"] == "not_applicable"
    life = await get_json(assistant_api, LIFE, headers)
    assert contents(life["upcoming"]) == contents(life["reminders"]) == ["Book flights"]
