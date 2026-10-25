"""Connected apps as memory sources (ADR-047): the user's upcoming calendar events become
plan memories, without any model.

When the user turns a source on, and then every ``SOURCE_SYNC_INTERVAL_SECONDS``, the
events of the next ``SYNC_DAYS`` are read through Composio. Each new event becomes an
accepted plan memory written by the app (``created_by = app``), due on its day; a changed
event updates its memory in place; an unchanged one is left alone. Which memory came from
which event is kept in ``synced_items``, so an event the user deleted the memory of is
not brought back. Events are data, not instructions: their text is stored, never acted on.
"""

import asyncio
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import (
    MemoryEventAction,
    MemoryOrigin,
    MemoryState,
    MemoryStatus,
    MemoryType,
    ToolConnectionStatus,
)
from app.domain.errors import DomainError, IntegrationNotConfiguredError, InvalidMemoryChangeError
from app.domain.normalization import normalize_for_matching
from app.domain.principal import Principal
from app.integrations.composio import ComposioClient
from app.models.memory import Memory
from app.models.synced_item import SyncedItem
from app.models.tool_connection import ToolConnection
from app.repositories.memory_repository import MemoryRepository
from app.repositories.tool_connection_repository import ToolConnectionRepository
from app.repositories.user_repository import UserRepository
from app.services.life_state import user_timezone
from app.services.memories import user_metadata

logger = structlog.get_logger(__name__)

CALENDAR: Final = "googlecalendar"
SOURCES: Final = (CALENDAR,)
EVENTS_TOOL: Final = "GOOGLECALENDAR_EVENTS_LIST"
SYNC_DAYS: Final = 14
MAX_EVENTS: Final = 100
_MAX_TEXT: Final = 300


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    id: str
    summary: str
    start: datetime | date
    location: str | None
    updated: str | None


@dataclass(frozen=True, slots=True)
class SourceView:
    app: str
    connected: bool
    enabled: bool
    last_synced_at: datetime | None
    error: str | None


@dataclass(frozen=True, slots=True)
class SyncReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0


def _event_lists(value: object, depth: int = 0) -> Iterable[list[Any]]:
    """Lists of events wherever the response nests them (``items``, ``events``, under
    ``data`` or ``response_data``)."""
    if depth > 4 or not isinstance(value, Mapping):
        return
    for key in ("items", "events"):
        found = value.get(key)
        if isinstance(found, list):
            yield found
    for key in ("data", "response_data", "result"):
        yield from _event_lists(value.get(key), depth + 1)


def _start(value: object) -> datetime | date | None:
    if not isinstance(value, Mapping):
        return None
    for key, parse in (("dateTime", datetime.fromisoformat), ("date", date.fromisoformat)):
        raw = value.get(key)
        if isinstance(raw, str):
            try:
                return parse(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
    return None


def parse_events(data: object) -> list[CalendarEvent]:
    """Confirmed events with an id, a title, and a start, as Composio returns them."""
    events: list[CalendarEvent] = []
    seen: set[str] = set()
    for found in _event_lists(data):
        for item in found:
            if not isinstance(item, Mapping) or item.get("status") == "cancelled":
                continue
            event_id, summary = item.get("id"), item.get("summary")
            start = _start(item.get("start"))
            if not isinstance(event_id, str) or not isinstance(summary, str) or start is None:
                continue
            if event_id in seen or not summary.strip():
                continue
            seen.add(event_id)
            location = item.get("location")
            updated = item.get("updated")
            events.append(
                CalendarEvent(
                    id=event_id[:255],
                    summary=" ".join(summary.split())[:_MAX_TEXT],
                    start=start,
                    location=location.strip()[:_MAX_TEXT]
                    if isinstance(location, str) and location.strip()
                    else None,
                    updated=updated[:64] if isinstance(updated, str) else None,
                )
            )
    return events


def event_memory(event: CalendarEvent, zone: ZoneInfo) -> tuple[str, date]:
    """The memory's text and due date for an event, in the user's timezone."""
    if isinstance(event.start, datetime):
        local = event.start.astimezone(zone) if event.start.tzinfo else event.start
        when = f"{local:%a} {local.day} {local:%b} at {local:%H:%M}"
        day = local.date()
    else:
        when = f"{event.start:%a} {event.start.day} {event.start:%b}, all day"
        day = event.start
    place = f", at {event.location}" if event.location else ""
    return f"{event.summary} ({when}{place})", day


class SourceSyncService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        composio: ComposioClient | None,
        *,
        default_timezone: str,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._composio = composio
        self._default_timezone = default_timezone
        self._clock = clock

    async def sources(self, principal: Principal) -> list[SourceView]:
        async with self._session_factory() as session:
            connections = ToolConnectionRepository(session)
            return [_view(app, await connections.get(principal.id, app)) for app in SOURCES]

    async def set_enabled(self, principal: Principal, app: str, *, enabled: bool) -> SourceView:
        """Turn a source on or off. Turning it on syncs at once and reports the outcome."""
        _require_source(app)
        async with transaction(self._session_factory) as session:
            connection = await ToolConnectionRepository(session).get(principal.id, app)
            if connection is None or connection.status != ToolConnectionStatus.CONNECTED.value:
                raise InvalidMemoryChangeError("Connect Google Calendar first.")
            connection.memory_sync_enabled = enabled
            if not enabled:
                connection.sync_error = None
        if enabled:
            await self.sync(principal, app)
        return (await self.sources_by_app(principal))[app]

    async def sources_by_app(self, principal: Principal) -> dict[str, SourceView]:
        return {view.app: view for view in await self.sources(principal)}

    async def sync(self, principal: Principal, app: str) -> SyncReport:
        """Read the app's items and bring the memories up to date. A failure is recorded
        on the connection (``sync_error``) and raised."""
        _require_source(app)
        if self._composio is None:
            raise IntegrationNotConfiguredError("Connected apps", "COMPOSIO_API_KEY")
        now = self._clock()
        try:
            events = await self._fetch(principal, now)
        except DomainError as error:
            await self._record(principal, app, now, error=error.message)
            raise
        async with transaction(self._session_factory) as session:
            zone = user_timezone(
                await UserRepository(session).get(principal.id), self._default_timezone
            )
            report = await _apply(session, principal.id, events, zone, now)
        await self._record(principal, app, now, error=None)
        logger.info("source_synced", app=app, created=report.created, updated=report.updated)
        return report

    async def sync_all(self) -> int:
        """Every enabled source of every user; one failure never stops the others."""
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(ToolConnection).where(
                    ToolConnection.memory_sync_enabled.is_(True),
                    ToolConnection.status == ToolConnectionStatus.CONNECTED.value,
                )
            )
            enabled = [(row.user_id, row.toolkit_slug) for row in rows]
        synced = 0
        for user_id, app in enabled:
            try:
                await self.sync(Principal(id=user_id, email=None, display_name=None), app)
                synced += 1
            except Exception:
                logger.exception("source_sync_failed", app=app)
        return synced

    async def _fetch(self, principal: Principal, now: datetime) -> list[CalendarEvent]:
        assert self._composio is not None
        accounts = await self._account_ids(principal)
        if not accounts:
            raise InvalidMemoryChangeError("Google Calendar is not connected any more.")
        session_id = await self._composio.create_session(str(principal.id), CALENDAR, accounts)
        execution = await self._composio.execute_tool(
            session_id,
            EVENTS_TOOL,
            {
                "calendarId": "primary",
                "timeMin": now.isoformat(),
                "timeMax": (now + timedelta(days=SYNC_DAYS)).isoformat(),
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": MAX_EVENTS,
            },
        )
        if not execution.successful:
            raise InvalidMemoryChangeError(
                f"Google Calendar could not be read: {execution.error or 'unknown error'}"
            )
        return parse_events(execution.data)[:MAX_EVENTS]

    async def _account_ids(self, principal: Principal) -> list[str]:
        assert self._composio is not None
        return [
            account.id
            for account in await self._composio.list_active_accounts(str(principal.id))
            if account.toolkit_slug == CALENDAR
        ]

    async def _record(
        self, principal: Principal, app: str, now: datetime, *, error: str | None
    ) -> None:
        async with transaction(self._session_factory) as session:
            connection = await ToolConnectionRepository(session).get(principal.id, app)
            if connection is not None:
                connection.last_synced_at = now
                connection.sync_error = error


async def _apply(
    session: AsyncSession,
    user_id: uuid.UUID,
    events: list[CalendarEvent],
    zone: ZoneInfo,
    now: datetime,
) -> SyncReport:
    memories = MemoryRepository(session)
    known = {
        item.external_id: item
        for item in await session.scalars(
            select(SyncedItem).where(
                SyncedItem.user_id == user_id,
                SyncedItem.source == CALENDAR,
                SyncedItem.external_id.in_([event.id for event in events]),
            )
        )
    }
    created = updated = unchanged = 0
    for event in events:
        content, day = event_memory(event, zone)
        item = known.get(event.id)
        if item is None:
            memory = _new_memory(user_id, content, day, now)
            await memories.add_memories([memory])
            await memories.add_event(
                memory.id, MemoryEventAction.CREATED, now=now, details={"by": CALENDAR}
            )
            session.add(
                SyncedItem(
                    id=new_uuid(),
                    user_id=user_id,
                    source=CALENDAR,
                    external_id=event.id,
                    external_updated=event.updated,
                    memory_id=memory.id,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1
            continue
        if item.external_updated == event.updated or item.memory_id is None:
            # Unchanged, or the user deleted its memory: leave it.
            unchanged += 1
            continue
        memory_row = await memories.get_owned(item.memory_id, user_id, for_update=True)
        item.external_updated = event.updated
        item.updated_at = now
        if memory_row is None or memory_row.status not in (
            MemoryStatus.PROPOSED.value,
            MemoryStatus.ACTIVE.value,
        ):
            unchanged += 1
            continue
        changes: dict[str, Any] = {}
        if memory_row.content != content:
            changes["content"] = {"from": memory_row.content, "to": content}
            memory_row.content = content
            memory_row.normalized_content = normalize_for_matching(content)
        if memory_row.due_on != day:
            changes["due_on"] = {
                "from": memory_row.due_on.isoformat() if memory_row.due_on else None,
                "to": day.isoformat(),
            }
            memory_row.due_on = day
        if changes:
            memory_row.updated_at = now
            await memories.add_event(
                memory_row.id,
                MemoryEventAction.EDITED,
                now=now,
                details={"by": CALENDAR, "changes": changes},
            )
            updated += 1
        else:
            unchanged += 1
    await session.flush()
    return SyncReport(created=created, updated=updated, unchanged=unchanged)


def _new_memory(user_id: uuid.UUID, content: str, day: date, now: datetime) -> Memory:
    metadata = user_metadata(sensitive=False)
    metadata["state"] = MemoryState.PLANNED.value
    return Memory(
        id=new_uuid(),
        memory_type=MemoryType.PLAN.value,
        content=content,
        normalized_content=normalize_for_matching(content),
        status=MemoryStatus.ACTIVE.value,
        metadata_=metadata,
        owner_id=user_id,
        created_by=MemoryOrigin.APP.value,
        due_on=day,
        created_at=now,
        updated_at=now,
    )


def _require_source(app: str) -> None:
    if app not in SOURCES:
        raise InvalidMemoryChangeError("Only Google Calendar can be a memory source for now.")


def _view(app: str, connection: ToolConnection | None) -> SourceView:
    return SourceView(
        app=app,
        connected=connection is not None
        and connection.status == ToolConnectionStatus.CONNECTED.value,
        enabled=connection is not None and connection.memory_sync_enabled,
        last_synced_at=connection.last_synced_at if connection else None,
        error=connection.sync_error if connection else None,
    )


class SourceSyncLoop:
    """Syncs every enabled source every ``interval_seconds`` while the API runs."""

    def __init__(self, service: SourceSyncService, *, interval_seconds: float) -> None:
        self._service = service
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="source-sync-loop")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self._service.sync_all()
            except Exception:
                # A failed pass must not end the loop; the next pass tries again.
                logger.exception("source_sync_pass_failed")
            await asyncio.sleep(self._interval_seconds)
