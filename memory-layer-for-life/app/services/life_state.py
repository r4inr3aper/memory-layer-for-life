"""Life state as the user sees and changes it: open items by when they are due, goals,
items gone quiet, reminders, and what got done lately; marking items done, dropping them,
opening them again; reminders Cooper sets on request; and the daily brief.

Sensitive items appear in the owner's own overview but never in anything posted to chat
(the brief, a reminder's text) or given to Cooper, because chat history reaches the model.
"""

import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.session import transaction
from app.domain.enums import (
    CloseReason,
    LifeBucket,
    MemoryEventAction,
    MemoryOrigin,
    MemoryState,
    MemoryStatus,
    MemoryType,
)
from app.domain.errors import InvalidMemoryChangeError, RecordNotFoundError
from app.domain.life_state import (
    LONG_TERM_TYPES,
    QUESTION_TYPES,
    REVIEW_NEWS_WINDOW,
    Brief,
    BriefInputs,
    BriefItem,
    BriefReminder,
    bucket_for,
    compose_brief,
    is_stale,
)
from app.domain.memory_policy import display_title
from app.domain.memory_review import ensure_live
from app.domain.principal import Principal
from app.models.app_user import AppUser
from app.models.memory import Memory
from app.repositories.life_repository import LifeRepository
from app.repositories.memory_repository import MemoryRepository
from app.repositories.user_repository import UserRepository
from app.services.memories import clean_content, new_user_memory, owned_memory, user_metadata
from app.services.queries import MemoryView

RECENTLY_DONE: Final = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class LifeOverview:
    today: date
    timezone: str
    # Tasks, plans, commitments, and intentions, by when they are due.
    buckets: Mapping[LifeBucket, tuple[MemoryView, ...]]
    goals: tuple[MemoryView, ...]
    stale_ids: frozenset[uuid.UUID]
    reminders: tuple[MemoryView, ...]
    recently_done: tuple[MemoryView, ...]
    # Open questions and unresolved problems: nothing to tick off.
    questions: tuple[MemoryView, ...] = ()
    # Open items from an imported chat that nobody has looked at: still relevant? They
    # stay out of the to-dos (an old export's tasks are rarely still open) until kept.
    triage: tuple[MemoryView, ...] = ()


def user_timezone(user: AppUser | None, default_timezone: str) -> ZoneInfo:
    name = user.timezone if user is not None and user.timezone else default_timezone
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError):
        return ZoneInfo(default_timezone)


class LifeStateService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        default_timezone: str,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._default_timezone = default_timezone
        self._clock = clock

    async def overview(
        self, principal: Principal, *, include_sensitive: bool = True
    ) -> LifeOverview:
        now = self._clock()
        async with self._session_factory() as session:
            user = await UserRepository(session).get(principal.id)
            zone = user_timezone(user, self._default_timezone)
            today = now.astimezone(zone).date()
            life = LifeRepository(session)
            items = await life.open_items(principal.id, include_sensitive=include_sensitive)
            reminders = await life.reminders(principal.id, include_sensitive=include_sensitive)
            done = await life.recently_closed(principal.id, since=now - RECENTLY_DONE)
            imported = await life.imported([memory.id for memory in items])

        buckets: dict[LifeBucket, list[MemoryView]] = defaultdict(list)
        goals: list[MemoryView] = []
        questions: list[MemoryView] = []
        triage: list[MemoryView] = []
        stale: set[uuid.UUID] = set()
        for memory in items:
            view = MemoryView.of(memory)
            kind = MemoryType(memory.memory_type)
            if memory.id in imported and memory.status == MemoryStatus.PROPOSED.value:
                triage.append(view)
                continue
            if is_stale(
                due_on=memory.due_on, last_activity=memory.updated_at, now=now, today=today
            ):
                stale.add(memory.id)
            if kind in LONG_TERM_TYPES:
                goals.append(view)
            elif kind in QUESTION_TYPES:
                questions.append(view)
            else:
                buckets[bucket_for(memory.due_on, today)].append(view)
        return LifeOverview(
            today=today,
            timezone=zone.key,
            buckets={bucket: tuple(buckets.get(bucket, ())) for bucket in LifeBucket},
            goals=tuple(goals),
            stale_ids=frozenset(stale),
            reminders=tuple(MemoryView.of(memory) for memory in reminders),
            recently_done=tuple(
                MemoryView.of(memory)
                for memory in done
                if memory.close_reason == CloseReason.DONE.value
            ),
            questions=tuple(questions),
            triage=tuple(triage),
        )

    async def complete(self, principal: Principal, memory_id: uuid.UUID) -> MemoryView:
        return await self._close(principal, memory_id, CloseReason.DONE)

    async def drop(self, principal: Principal, memory_id: uuid.UUID) -> MemoryView:
        return await self._close(principal, memory_id, CloseReason.DROPPED)

    async def reopen(self, principal: Principal, memory_id: uuid.UUID) -> MemoryView:
        now = self._clock()
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            memory = await owned_memory(memories, principal, memory_id)
            ensure_live(MemoryStatus(memory.status))
            if memory.closed_at is None:
                return MemoryView.of(memory)
            reason = memory.close_reason
            memory.closed_at = None
            memory.close_reason = None
            if memory.metadata_.get("state") == MemoryState.DONE.value:
                memory.metadata_ = {**memory.metadata_, "state": MemoryState.OPEN.value}
            memory.updated_at = now
            await memories.add_event(
                memory.id, MemoryEventAction.REOPENED, now=now, details={"was": reason}
            )
            return MemoryView.of(memory)

    async def snooze(
        self, principal: Principal, memory_id: uuid.UUID, remind_at: datetime
    ) -> MemoryView:
        """Remind the user of an open item later. A closed item opens again."""
        now = self._clock()
        if remind_at <= now:
            raise InvalidMemoryChangeError("That time has already passed. Pick a time later.")
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            memory = await owned_memory(memories, principal, memory_id)
            ensure_live(MemoryStatus(memory.status))
            before = memory.remind_at
            if memory.closed_at is not None:
                memory.closed_at = None
                memory.close_reason = None
                if memory.metadata_.get("state") == MemoryState.DONE.value:
                    memory.metadata_ = {**memory.metadata_, "state": MemoryState.OPEN.value}
            memory.remind_at = remind_at
            memory.updated_at = now
            await memories.add_event(
                memory.id,
                MemoryEventAction.SCHEDULED,
                now=now,
                details={
                    "changes": {
                        "remind_at": {
                            "from": before.isoformat() if before else None,
                            "to": remind_at.isoformat(),
                        }
                    }
                },
            )
            return MemoryView.of(memory)

    async def create_reminder(
        self,
        principal: Principal,
        *,
        content: str,
        remind_at: datetime,
        due_on: date | None,
        origin: MemoryOrigin = MemoryOrigin.ASSISTANT,
    ) -> MemoryView:
        """A task the user asked to be reminded of, saved as accepted with its reminder."""
        now = self._clock()
        if remind_at <= now:
            raise InvalidMemoryChangeError("That time has already passed. Pick a time later.")
        text = clean_content(content)
        metadata = user_metadata(sensitive=False)
        metadata["state"] = MemoryState.OPEN.value
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            memory = new_user_memory(
                owner_id=principal.id,
                memory_type=MemoryType.TASK,
                content=text,
                metadata=metadata,
                now=now,
            )
            memory.created_by = origin.value
            memory.remind_at = remind_at
            memory.due_on = due_on
            await memories.add_memories([memory])
            await memories.add_event(
                memory.id,
                MemoryEventAction.CREATED,
                now=now,
                details={"by": origin.value, "remind_at": remind_at.isoformat()},
            )
            return MemoryView.of(memory)

    async def brief(self, principal: Principal) -> Brief:
        """Today's brief as it stands now, without sending it."""
        async with self._session_factory() as session:
            user = await UserRepository(session).get(principal.id)
            if user is None:
                raise RecordNotFoundError("User", str(principal.id))
            return await compose_user_brief(session, user, self._clock(), self._default_timezone)

    async def _close(
        self, principal: Principal, memory_id: uuid.UUID, reason: CloseReason
    ) -> MemoryView:
        now = self._clock()
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            memory = await owned_memory(memories, principal, memory_id)
            ensure_live(MemoryStatus(memory.status))
            if memory.close_reason == reason.value:
                return MemoryView.of(memory)
            memory.closed_at = now
            memory.close_reason = reason.value
            memory.remind_at = None
            if reason is CloseReason.DONE:
                memory.metadata_ = {**memory.metadata_, "state": MemoryState.DONE.value}
            # Acting on a memory confirms it.
            memory.status = MemoryStatus.ACTIVE.value
            memory.updated_at = now
            action = (
                MemoryEventAction.COMPLETED
                if reason is CloseReason.DONE
                else MemoryEventAction.DROPPED
            )
            await memories.add_event(memory.id, action, now=now)
            return MemoryView.of(memory)


async def compose_user_brief(
    session: AsyncSession, user: AppUser, now: datetime, default_timezone: str
) -> Brief:
    """The user's brief for their local today, from non-sensitive items only."""
    zone = user_timezone(user, default_timezone)
    local_now = now.astimezone(zone)
    today = local_now.date()
    life = LifeRepository(session)
    open_items = await life.open_items(user.id, include_sensitive=False)
    imported = await life.imported([memory.id for memory in open_items])
    # Questions and imported items nobody has looked at are not the day's to-dos.
    items = [
        memory
        for memory in open_items
        if MemoryType(memory.memory_type) not in QUESTION_TYPES
        and not (memory.id in imported and memory.status == MemoryStatus.PROPOSED.value)
    ]
    end_of_day = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=zone)
    reminders = await life.reminders(user.id, include_sensitive=False, before=end_of_day)
    review = await life.count_proposed_since(user.id, now - REVIEW_NEWS_WINDOW)
    last_week_done = 0
    if today.weekday() == 0:
        midnight = datetime.combine(today, datetime.min.time(), tzinfo=zone)
        last_week_done = sum(
            1
            for memory in await life.recently_closed(user.id, since=midnight - timedelta(days=7))
            if memory.close_reason == CloseReason.DONE.value
            and memory.closed_at is not None
            and memory.closed_at < midnight
        )

    def item(memory: Memory) -> BriefItem:
        return BriefItem(
            memory_id=memory.id,
            content=display_title(memory.content, memory.metadata_),
            due_on=memory.due_on,
        )

    actionable = [m for m in items if MemoryType(m.memory_type) not in LONG_TERM_TYPES]
    yesterday = today - timedelta(days=1)
    return compose_brief(
        BriefInputs(
            today=today,
            user_name=_first_name(user.display_name),
            due_today=[item(m) for m in actionable if m.due_on == today],
            overdue=[item(m) for m in actionable if m.due_on is not None and m.due_on < yesterday],
            follow_ups=[item(m) for m in actionable if m.due_on == yesterday],
            upcoming=[
                item(m)
                for m in actionable
                if m.due_on is not None and bucket_for(m.due_on, today) is LifeBucket.UPCOMING
            ],
            stale=[
                item(m)
                for m in items
                if is_stale(due_on=m.due_on, last_activity=m.updated_at, now=now, today=today)
            ],
            reminders=[
                BriefReminder(
                    memory_id=m.id,
                    content=display_title(m.content, m.metadata_),
                    at=m.remind_at.astimezone(zone).time() if m.remind_at else local_now.time(),
                )
                for m in reminders
                if m.remind_at is not None and m.remind_at > now
            ],
            review_count=review,
            last_week_done=last_week_done,
        )
    )


def _first_name(display_name: str | None) -> str | None:
    if not display_name or not display_name.strip():
        return None
    return display_name.split()[0]
