"""New memory sources against PostgreSQL: WhatsApp imports through the real pipeline,
photos and PDFs read by a fake reader, and calendar events from a fake Composio. The clock
starts on Thursday 1 October 2026 at 12:00 UTC."""

import base64
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.domain.enums import MemoryType, MessageSource, ProcessingStatus
from app.domain.errors import FileReadError
from app.integrations.assistant.base import Attachment
from app.integrations.composio import ComposioExecution
from app.integrations.llm_calls import LlmCallContext
from app.models.raw_message import RawMessage
from app.services.processing.runner import PipelineLoop
from app.services.source_sync import EVENTS_TOOL
from tests.integration.conftest import AssistantHarness, AssistantHarnessFactory
from tests.support.app_api import API, connect_app
from tests.support.extraction import evidence, extraction, memory
from tests.support.memories_api import MEMORIES, get_json, patch_json, post_json, sign_up

CHAT = """28/09/26, 9:41 pm - Priya: Are we still on for Sunday?
28/09/26, 9:43 pm - Ada: Yes, lunch at 1. I'll bring the cake
29/09/26, 8:05 am - Raju: Who's driving?
29/09/26, 6:30 pm - Ada: Raju owes me 500 for the tickets
29/09/26, 6:31 pm - Priya: <Media omitted>
"""


def encoded(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class FakeReader:
    def __init__(self, text: str = "Receipt: Coffee 250\nDescription: A cafe receipt.") -> None:
        self.text = text
        self.calls: list[tuple[Attachment, LlmCallContext]] = []
        self.fail = False

    async def read(self, file: Attachment, *, context: LlmCallContext) -> str:
        self.calls.append((file, context))
        if self.fail:
            raise FileReadError("This file could not be read.")
        return self.text


# --- WhatsApp imports ------------------------------------------------------------------


async def test_a_whatsapp_chat_is_previewed_then_imported_as_conversations(
    assistant_api: AssistantHarness,
) -> None:
    _, headers = await sign_up(assistant_api)
    await patch_json(assistant_api, f"{API}/me", headers, {"timezone": "Asia/Kolkata"})

    preview = await post_json(
        assistant_api,
        f"{API}/me/imports/whatsapp",
        headers,
        {"file_name": "WhatsApp Chat with Priya.txt", "data_base64": encoded(CHAT)},
        status=201,
    )

    assert preview["status"] == "previewed"
    assert preview["message_count"] == 4
    assert preview["all_conversations"] == 3
    assert [(p["name"], p["messages"], p["conversations"]) for p in preview["participants"]] == [
        ("Ada", 2, 2),
        ("Priya", 1, 1),
        ("Raju", 1, 1),
    ]
    assert preview["first_message_at"] == "2026-09-28T21:41:00+05:30"
    assert preview["cost_per_conversation"] is None or float(preview["cost_per_conversation"]) >= 0
    again = await post_json(
        assistant_api,
        f"{API}/me/imports/whatsapp",
        headers,
        {"file_name": "same.txt", "data_base64": encoded(CHAT)},
        status=201,
    )
    assert again["id"] == preview["id"]
    async with assistant_api.container.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RawMessage)) == 0

    wrong = await assistant_api.client.post(
        f"{API}/me/imports/{preview['id']}/start", json={"me": "Nobody"}, headers=headers
    )
    assert wrong.status_code == 422

    assistant_api.extractor.use_script(
        extraction(
            memory(
                "Lunch with Priya on Sunday at 1.",
                memory_type=MemoryType.PLAN,
                evidence_refs=[evidence(1, "lunch at 1")],
            )
        ),
        extraction(
            memory(
                "Raju owes the user 500 for the tickets.",
                memory_type=MemoryType.FINANCIAL_NOTE,
                evidence_refs=[evidence(0, "Raju owes me 500")],
            )
        ),
    )
    started = await post_json(
        assistant_api, f"{API}/me/imports/{preview['id']}/start", headers, {"me": "Ada"}
    )

    assert (started["status"], started["unit_count"], started["owner_name"]) == ("queued", 2, "Ada")
    assert started["progress"] == {"done": 0, "failed": 0, "waiting": 2, "memories": 0}
    async with assistant_api.container.session_factory() as session:
        lines = list(
            await session.scalars(
                select(RawMessage.content)
                .where(RawMessage.source == MessageSource.WHATSAPP_IMPORT.value)
                .order_by(RawMessage.source_created_at)
            )
        )
    assert lines == [
        "Priya: Are we still on for Sunday?",
        "Me: Yes, lunch at 1. I'll bring the cake",
        "Me: Raju owes me 500 for the tickets",
    ]

    loop = PipelineLoop(assistant_api.container.pipeline_runner, interval_seconds=60, batch_size=10)
    outcomes = await loop.run_once()

    assert [outcome.status for outcome in outcomes] == [ProcessingStatus.SUCCEEDED] * 2
    progress = (await get_json(assistant_api, f"{API}/me/imports/{preview['id']}", headers))[
        "progress"
    ]
    assert progress == {"done": 2, "failed": 0, "waiting": 0, "memories": 2}
    owned = await get_json(assistant_api, MEMORIES, headers)
    assert owned["total"] == 2
    refused = await assistant_api.client.post(
        f"{API}/me/imports/whatsapp",
        json={"file_name": "again.txt", "data_base64": encoded(CHAT)},
        headers=headers,
    )
    assert refused.status_code == 422
    assert "already imported" in refused.json()["message"]
    _, stranger = await sign_up(assistant_api, "Eve")
    assert await get_json(assistant_api, f"{API}/me/imports", stranger) == []
    missing = await assistant_api.client.get(f"{API}/me/imports/{preview['id']}", headers=stranger)
    assert missing.status_code == 404


async def test_an_import_can_leave_out_old_messages_and_cap_its_size(
    assistant_api: AssistantHarness,
) -> None:
    _, headers = await sign_up(assistant_api)
    preview = await post_json(
        assistant_api,
        f"{API}/me/imports/whatsapp",
        headers,
        {"file_name": "chat.txt", "data_base64": encoded(CHAT)},
        status=201,
    )

    started = await post_json(
        assistant_api,
        f"{API}/me/imports/{preview['id']}/start",
        headers,
        {
            "me": "Ada",
            "since": "2026-09-29",
            "only_my_conversations": False,
            "max_conversations": 1,
        },
    )

    assert started["unit_count"] == 1
    assert started["since"] == "2026-09-29"


async def test_files_that_are_not_chats_are_refused(assistant_api: AssistantHarness) -> None:
    _, headers = await sign_up(assistant_api)

    for body in (
        {"file_name": "notes.txt", "data_base64": encoded("just my notes")},
        {"file_name": "chat.txt", "data_base64": "not base64!"},
    ):
        response = await assistant_api.client.post(
            f"{API}/me/imports/whatsapp", json=body, headers=headers
        )
        assert response.status_code == 422, body


# --- Photos and PDFs -------------------------------------------------------------------


async def test_a_photo_is_read_once_and_becomes_memories(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    reader = FakeReader()
    async with assistant_api_with(document_reader=reader) as harness:
        principal, headers = await sign_up(harness)
        harness.extractor.use_script(
            extraction(
                memory(
                    "Spent 250 on coffee.",
                    memory_type=MemoryType.FINANCIAL_NOTE,
                    evidence_refs=[evidence(0, "Coffee 250")],
                )
            )
        )
        body = {
            "file_name": "receipt.jpg",
            "media_type": "image/jpeg",
            "data_base64": base64.b64encode(b"\xff\xd8 a jpeg").decode(),
        }

        saved = await post_json(harness, f"{MEMORIES}/from-file", headers, body, status=201)
        await harness.container.background.wait()
        again = await post_json(harness, f"{MEMORIES}/from-file", headers, body, status=201)

        assert saved["created"] is True
        assert saved["text"].startswith("From the file receipt.jpg:")
        assert again == {**saved, "created": False}
        assert len(reader.calls) == 1
        file, context = reader.calls[0]
        assert (file.media_type, context.user_id) == ("image/jpeg", principal.id)
        memories = await get_json(harness, MEMORIES, headers)
        assert [item["content"] for item in memories["items"]] == ["Spent 250 on coffee."]
        usage = await get_json(harness, f"{API}/me/usage", headers)
        assert usage["prompts_used"] == 1


async def test_files_that_cannot_be_used_are_refused(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    reader = FakeReader()
    async with assistant_api_with(document_reader=reader) as harness:
        _, headers = await sign_up(harness)
        data = base64.b64encode(b"bytes").decode()
        unsupported = await harness.client.post(
            f"{MEMORIES}/from-file",
            json={"file_name": "a.docx", "media_type": "application/msword", "data_base64": data},
            headers=headers,
        )
        reader.fail = True
        unreadable = await harness.client.post(
            f"{MEMORIES}/from-file",
            json={"file_name": "a.pdf", "media_type": "application/pdf", "data_base64": data},
            headers=headers,
        )

    assert unsupported.status_code == 422
    assert unreadable.status_code == 502
    assert unreadable.json()["message"] == "This file could not be read."


async def test_reading_files_needs_a_model(sign_in_only_api: AssistantHarness) -> None:
    _, headers = await sign_up(sign_in_only_api)

    response = await sign_in_only_api.client.post(
        f"{MEMORIES}/from-file",
        json={"file_name": "a.png", "media_type": "image/png", "data_base64": "aGk="},
        headers=headers,
    )

    assert response.status_code == 503


# --- Calendar as a source --------------------------------------------------------------


def events(*items: dict[str, object]) -> ComposioExecution:
    return ComposioExecution(
        successful=True, data={"response_data": {"items": list(items)}}, error=None
    )


def event(
    event_id: str, summary: str, start: str, updated: str = "v1", **extra: object
) -> dict[str, object]:
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start},
        "updated": updated,
        **extra,
    }


async def test_calendar_events_become_plans_and_stay_in_sync(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    await patch_json(assistant_api, f"{API}/me", headers, {"timezone": "Asia/Kolkata"})
    await connect_app(assistant_api, principal.id, headers, "googlecalendar")
    assistant_api.composio.execution = events(
        event("e1", "Dentist", "2026-10-03T04:30:00Z", location="Smile Clinic"),
        {"id": "e2", "summary": "Holiday", "start": {"date": "2026-10-05"}, "updated": "v1"},
        {
            "id": "e3",
            "summary": "Cancelled thing",
            "start": {"date": "2026-10-06"},
            "status": "cancelled",
        },
    )

    source = await patch_json(
        assistant_api, f"{API}/me/sources/googlecalendar", headers, {"enabled": True}
    )

    assert (source["enabled"], source["error"]) == (True, None)
    assert source["last_synced_at"] is not None
    [(_, tool, arguments)] = assistant_api.composio.executions
    assert tool == EVENTS_TOOL
    assert arguments["timeMin"] == datetime(2026, 10, 1, 12, tzinfo=UTC).isoformat()
    life = await get_json(assistant_api, f"{API}/me/life", headers)
    assert [item["content"] for item in life["upcoming"]] == [
        "Dentist (Sat 3 Oct at 10:00, at Smile Clinic)",
        "Holiday (Mon 5 Oct, all day)",
    ]
    dentist = life["upcoming"][0]
    assert (dentist["created_by"], dentist["memory_type"], dentist["due_on"]) == (
        "app",
        "plan",
        "2026-10-03",
    )

    # A moved event updates its memory; a deleted memory is not brought back.
    await assistant_api.client.delete(f"{MEMORIES}/{life['upcoming'][1]['id']}", headers=headers)
    assistant_api.composio.execution = events(
        event("e1", "Dentist", "2026-10-04T04:30:00Z", updated="v2", location="Smile Clinic"),
        {"id": "e2", "summary": "Holiday", "start": {"date": "2026-10-05"}, "updated": "v2"},
    )
    await post_json(assistant_api, f"{API}/me/sources/googlecalendar/sync", headers)

    life = await get_json(assistant_api, f"{API}/me/life", headers)
    assert [item["content"] for item in life["upcoming"]] == [
        "Dentist (Sun 4 Oct at 10:00, at Smile Clinic)"
    ]
    history = (await get_json(assistant_api, f"{MEMORIES}/{dentist['id']}", headers))["history"]
    assert [entry["action"] for entry in history] == ["created", "edited"]


async def test_a_failed_sync_is_reported_on_the_source(assistant_api: AssistantHarness) -> None:
    principal, headers = await sign_up(assistant_api)
    await connect_app(assistant_api, principal.id, headers, "googlecalendar")
    assistant_api.composio.execution = ComposioExecution(
        successful=False, data=None, error="token expired"
    )

    response = await assistant_api.client.patch(
        f"{API}/me/sources/googlecalendar", json={"enabled": True}, headers=headers
    )

    assert response.status_code == 422
    [source] = await get_json(assistant_api, f"{API}/me/sources", headers)
    assert source["enabled"] is True
    assert source["error"] == "Google Calendar could not be read: token expired"


async def test_a_source_needs_its_app_connected(assistant_api: AssistantHarness) -> None:
    _, headers = await sign_up(assistant_api)

    response = await assistant_api.client.patch(
        f"{API}/me/sources/googlecalendar", json={"enabled": True}, headers=headers
    )
    other = await assistant_api.client.patch(
        f"{API}/me/sources/gmail", json={"enabled": True}, headers=headers
    )

    assert response.status_code == other.status_code == 422
    assert await get_json(assistant_api, f"{API}/me/sources", headers) == [
        {
            "app": "googlecalendar",
            "connected": False,
            "enabled": False,
            "last_synced_at": None,
            "error": None,
        }
    ]
