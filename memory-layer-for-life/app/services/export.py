"""A copy of everything the app holds for a user, as one JSON document they can keep.

It holds the account and assistant settings, every memory (whatever its status, sensitive
ones included and marked) with its evidence, entities, and history, the people and things
in them, every chat with its messages, schedules with their runs, which apps are
connected (never their credentials), and daily usage. Times are ISO 8601 in UTC.

Read in one transaction, so the parts agree with each other.
"""

import uuid
from collections import defaultdict
from datetime import date, datetime, time
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.domain.enums import Sensitivity
from app.domain.errors import RecordNotFoundError
from app.domain.principal import Principal
from app.models.memory import Memory
from app.repositories.document_repository import DocumentRepository
from app.repositories.export_repository import ExportRepository
from app.repositories.link_repository import LinkRepository
from app.repositories.memory_repository import MemoryRepository

EXPORT_FORMAT: Final = "muse-export"
EXPORT_VERSION: Final = 1

Json = dict[str, Any]


class ExportService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, clock: Clock = utc_now
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def export(self, principal: Principal) -> Json:
        async with self._session_factory() as session, session.begin():
            data = ExportRepository(session)
            user = await data.user(principal.id)
            if user is None:
                raise RecordNotFoundError("User", str(principal.id))
            memories = await data.memories(principal.id)
            events = await MemoryRepository(session).events_for_owner(principal.id)
            entities = await data.entities(principal.id)
            threads = await data.threads(principal.id)
            messages = await data.messages(principal.id)
            schedules = await data.schedules(principal.id)
            runs = await data.schedule_runs(principal.id)
            connections = await data.connections(principal.id)
            usage = await data.usage(principal.id)
            documents = DocumentRepository(session)
            files = [
                (document, await documents.chunks(document.id))
                for document in await documents.list_for(principal.id)
            ]
            links = await LinkRepository(session).list_for(principal.id)

            history: dict[uuid.UUID, list[Json]] = defaultdict(list)
            for event in events:
                history[event.memory_id].append(
                    {
                        "action": event.action,
                        "details": event.details,
                        "at": _time(event.created_at),
                    }
                )
            by_thread: dict[uuid.UUID, list[Json]] = defaultdict(list)
            for message in messages:
                by_thread[message.thread_id].append(
                    {
                        "id": str(message.id),
                        "role": message.role,
                        "content": message.content,
                        "sent_at": _time(message.created_at),
                    }
                )
            by_schedule: dict[uuid.UUID, list[Json]] = defaultdict(list)
            for run in runs:
                by_schedule[run.scheduled_task_id].append(
                    {
                        "trigger": run.trigger,
                        "status": run.status,
                        "scheduled_for": _time(run.scheduled_for),
                        "started_at": _time(run.started_at),
                        "finished_at": _time(run.finished_at),
                        "summary": run.summary,
                        "error": run.error_message,
                    }
                )

            return {
                "format": EXPORT_FORMAT,
                "version": EXPORT_VERSION,
                "exported_at": _time(self._clock()),
                "account": {
                    "id": str(user.id),
                    "email": user.email,
                    "display_name": user.display_name,
                    "assistant_name": user.assistant_name,
                    "assistant_subtitle": user.assistant_subtitle,
                    "notifications_enabled": user.notifications_enabled,
                    "memory_capture_enabled": user.memory_capture_enabled,
                    "timezone": user.timezone,
                    "brief_enabled": user.brief_enabled,
                    "brief_time": _time(user.brief_time),
                    "reminders_enabled": user.reminders_enabled,
                    "created_at": _time(user.created_at),
                },
                "memories": [_memory(memory, history.get(memory.id, [])) for memory in memories],
                "people": [
                    {
                        "id": str(entity.id),
                        "type": entity.entity_type,
                        "name": entity.canonical_name,
                        "status": entity.status,
                        "merged_into_id": _id(entity.merged_into_id),
                        "created_at": _time(entity.created_at),
                    }
                    for entity in entities
                ],
                "chats": [
                    {
                        "id": str(thread.id),
                        "kind": thread.kind,
                        "title": thread.title,
                        "created_at": _time(thread.created_at),
                        "messages": by_thread.get(thread.id, []),
                    }
                    for thread in threads
                ],
                "schedules": [
                    {
                        "id": str(task.id),
                        "title": task.title,
                        "task": task.task,
                        "frequency": task.frequency,
                        "local_time": _time(task.local_time),
                        "weekdays": task.weekdays,
                        "day_of_month": task.day_of_month,
                        "start_date": _time(task.start_date),
                        "interval_hours": task.interval_hours,
                        "timezone": task.timezone,
                        "delivery": task.delivery,
                        "delivery_target": task.delivery_target,
                        "status": task.status,
                        "created_at": _time(task.created_at),
                        "runs": by_schedule.get(task.id, []),
                    }
                    for task in schedules
                ],
                "connected_apps": [
                    {
                        "app": connection.toolkit_slug,
                        "status": connection.status,
                        "account": connection.connected_email or connection.connected_label,
                        "connected_at": _time(connection.connected_at),
                    }
                    for connection in connections
                ],
                "usage": [
                    {
                        "day": _time(day.day),
                        "chat_messages": day.chat_messages,
                        "scheduled_runs": day.scheduled_runs,
                    }
                    for day in usage
                ],
                "documents": [
                    {
                        "id": str(document.id),
                        "title": document.title,
                        "file_name": document.file_name,
                        "is_resume": document.is_resume,
                        # The file itself is not in the export; the app can download it.
                        "has_file": document.has_file,
                        "created_at": _time(document.created_at),
                        "text": "\n\n".join(chunk.content for chunk in chunks),
                    }
                    for document, chunks in files
                ],
                "links": [
                    {
                        "id": str(link.id),
                        "url": link.url,
                        "title": link.title,
                        "kind": link.kind,
                        "created_at": _time(link.created_at),
                    }
                    for link in links
                ],
            }


def _memory(memory: Memory, history: list[Json]) -> Json:
    return {
        "id": str(memory.id),
        "type": memory.memory_type,
        "content": memory.content,
        "status": memory.status,
        "created_by": memory.created_by,
        "sensitive": memory.metadata_.get("sensitivity") == Sensitivity.SENSITIVE.value,
        "confidence": memory.confidence,
        "observed_at": _time(memory.observed_at),
        "valid_from": _time(memory.valid_from),
        "valid_until": _time(memory.valid_until),
        "supersedes_memory_id": _id(memory.supersedes_memory_id),
        "due_on": _time(memory.due_on),
        "remind_at": _time(memory.remind_at),
        "closed_at": _time(memory.closed_at),
        "close_reason": memory.close_reason,
        "details": memory.metadata_,
        "created_at": _time(memory.created_at),
        "updated_at": _time(memory.updated_at),
        "evidence": [
            {
                "message_id": str(source.raw_message_id),
                "role": source.source_role,
                "quote": source.evidence_text,
                "message": source.raw_message.content,
                "sent_at": _time(source.raw_message.source_created_at),
            }
            for source in sorted(memory.sources, key=lambda source: str(source.raw_message_id))
        ],
        "people": [
            {"id": str(link.entity_id), "name": link.entity.canonical_name}
            for link in sorted(memory.memory_entities, key=lambda link: str(link.entity_id))
        ],
        "history": history,
    }


def _time(value: datetime | date | time | None) -> str | None:
    return value.isoformat() if value is not None else None


def _id(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None
