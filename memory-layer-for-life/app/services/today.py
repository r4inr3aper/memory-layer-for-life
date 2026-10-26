"""Today: the Feed's cards, each something to act on (ADR-048, ``app.domain.today``).

Computed on request from the user's own records, without a model. Shown to the user only,
so sensitive memories are included and marked, as in the To do list.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.domain.enums import MemoryOrigin, MemoryStatus, MemoryType
from app.domain.life_state import LONG_TERM_TYPES, QUESTION_TYPES, REVIEW_NEWS_WINDOW
from app.domain.principal import Principal
from app.domain.today import (
    MAX_MEETINGS,
    MAX_PROMISES,
    MAX_RELATED,
    MAX_TO_CONFIRM,
    RESURFACE_AFTER,
    RESURFACE_TYPES,
    RESURFACE_UNTIL,
    ActionCandidate,
    names_in,
    next_actions,
    pick_of_the_day,
)
from app.models.memory import Memory
from app.repositories.life_repository import LifeRepository
from app.repositories.memory_repository import MemoryRepository
from app.repositories.user_repository import UserRepository
from app.services.life_state import user_timezone
from app.services.queries import MemoryView

# Memories waiting for review are offered for confirming while they are this recent.
_TO_CONFIRM_WINDOW = timedelta(days=14)


@dataclass(frozen=True, slots=True)
class Promise:
    memory: MemoryView
    people: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Meeting:
    event: MemoryView
    people: tuple[str, ...]
    # What the user's memories say about those people, newest first.
    related: tuple[MemoryView, ...]


@dataclass(frozen=True, slots=True)
class TodayView:
    today: date
    timezone: str
    next_actions: tuple[MemoryView, ...]
    promises: tuple[Promise, ...]
    meetings: tuple[Meeting, ...]
    resurface: MemoryView | None
    to_confirm: tuple[MemoryView, ...]
    # Memories made in the last week that wait for review.
    review_count: int


class TodayService:
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

    async def today(self, principal: Principal) -> TodayView:
        now = self._clock()
        async with self._session_factory() as session:
            user = await UserRepository(session).get(principal.id)
            zone = user_timezone(user, self._default_timezone)
            today = now.astimezone(zone).date()
            life = LifeRepository(session)

            open_items = await life.open_items(principal.id, include_sensitive=True)
            imported = await life.imported([item.id for item in open_items])
            # Imported items nobody looked at, and questions, are not things to do today.
            items = [
                item
                for item in open_items
                if MemoryType(item.memory_type) not in QUESTION_TYPES
                and not (item.id in imported and item.status == MemoryStatus.PROPOSED.value)
            ]
            people_of = await life.people_linked([item.id for item in items])

            events = [
                item
                for item in items
                if item.created_by == MemoryOrigin.APP.value
                and item.due_on is not None
                and today <= item.due_on <= today + timedelta(days=1)
            ][:MAX_MEETINGS]
            meetings = await self._meetings(session, principal.id, events)

            todos = [
                item
                for item in items
                if MemoryType(item.memory_type) not in LONG_TERM_TYPES
                and item.created_by != MemoryOrigin.APP.value
            ]
            ranked = next_actions(
                [
                    ActionCandidate(
                        memory_id=item.id,
                        due_on=item.due_on,
                        remind_on=item.remind_at.astimezone(zone).date()
                        if item.remind_at is not None
                        else None,
                        with_person=bool(people_of.get(item.id)),
                    )
                    for item in todos
                ],
                today,
            )
            by_id = {item.id: item for item in todos}
            promises = [
                Promise(MemoryView.of(item), tuple(people_of[item.id]))
                for item in todos
                if people_of.get(item.id) and item.id not in ranked
            ][:MAX_PROMISES]

            resurfacing = await life.resurfacing(
                principal.id,
                kinds=[kind.value for kind in RESURFACE_TYPES],
                created_between=(now - RESURFACE_UNTIL, now - RESURFACE_AFTER),
                untouched_since=now - RESURFACE_AFTER,
            )
            pick = pick_of_the_day(resurfacing, today)
            resurface = (
                await MemoryRepository(session).get_owned(pick, principal.id)
                if pick is not None
                else None
            )
            to_confirm = await life.recent_proposed(
                principal.id, since=now - _TO_CONFIRM_WINDOW, limit=MAX_TO_CONFIRM
            )
            review_count = await life.count_proposed_since(principal.id, now - REVIEW_NEWS_WINDOW)

        return TodayView(
            today=today,
            timezone=zone.key,
            next_actions=tuple(MemoryView.of(by_id[memory_id]) for memory_id in ranked),
            promises=tuple(promises),
            meetings=tuple(meetings),
            resurface=MemoryView.of(resurface) if resurface is not None else None,
            to_confirm=tuple(MemoryView.of(memory) for memory in to_confirm),
            review_count=review_count,
        )

    async def _meetings(
        self, session: AsyncSession, owner_id: uuid.UUID, events: list[Memory]
    ) -> list[Meeting]:
        """Each event with what the user's memories say about the people it names."""
        if not events:
            return []
        life = LifeRepository(session)
        people = await life.people(owner_id)
        meetings = []
        for event in events:
            named = names_in(event.content, people)
            related = await life.memories_about(
                owner_id,
                named,
                exclude=[event.id],
                include_sensitive=True,
                limit=MAX_RELATED,
            )
            meetings.append(
                Meeting(
                    event=MemoryView.of(event),
                    people=tuple(people[entity_id] for entity_id in named),
                    related=tuple(MemoryView.of(memory) for memory in related),
                )
            )
        return meetings
