"""Insights for one user, computed on request from their memories (``app.domain.insights``),
and feedback on them.

Nothing here calls a model. Insights are shown to their owner only, so sensitive memories
count like any other; the Feed never reaches Cooper.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.session import transaction
from app.domain.enums import CloseReason, InsightKind, MemoryType
from app.domain.insights import (
    Closure,
    Insight,
    InsightInputs,
    Mention,
    MoneyNote,
    OpenGoal,
    compute_insights,
)
from app.domain.life_state import LONG_TERM_TYPES
from app.domain.principal import Principal
from app.repositories.insight_repository import InsightRepository
from app.repositories.life_repository import LifeRepository
from app.repositories.user_repository import UserRepository
from app.services.life_state import user_timezone

# How far back mentions are read: long enough to notice someone who went quiet.
MENTION_HISTORY: Final = timedelta(days=180)
CLOSURE_HISTORY: Final = timedelta(days=60)
MONEY_HISTORY: Final = timedelta(days=70)


@dataclass(frozen=True, slots=True)
class Usefulness:
    kind: InsightKind
    useful: int
    not_useful: int


class InsightService:
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

    async def list_insights(self, principal: Principal) -> list[Insight]:
        now = self._clock()
        async with self._session_factory() as session:
            user = await UserRepository(session).get(principal.id)
            zone = user_timezone(user, self._default_timezone)
            today = now.astimezone(zone).date()
            data = InsightRepository(session)
            money = await data.money_notes(principal.id, since=now - MONEY_HISTORY)
            mentions = await data.mentions(principal.id, since=now - MENTION_HISTORY)
            closures = await data.closures(principal.id, since=now - CLOSURE_HISTORY)
            hidden = await data.hidden_keys(principal.id)
            open_items = await LifeRepository(session).open_items(
                principal.id, include_sensitive=True
            )
        return compute_insights(
            InsightInputs(
                today=today,
                now=now,
                money=[
                    MoneyNote(
                        memory_id=memory_id,
                        happened_on=happened.astimezone(zone).date(),
                        amount=amount,
                        currency=currency,
                        category=category,
                    )
                    for memory_id, happened, amount, currency, category in money
                ],
                mentions=[
                    Mention(
                        memory_id=memory_id,
                        entity_id=entity_id,
                        entity_name=name,
                        entity_type=entity_type,
                        happened_at=happened,
                    )
                    for memory_id, entity_id, name, entity_type, happened in mentions
                ],
                closures=[
                    Closure(
                        memory_id=memory_id,
                        closed_on=closed_at.astimezone(zone).date(),
                        done=reason == CloseReason.DONE.value,
                    )
                    for memory_id, closed_at, reason in closures
                ],
                overdue_ids=[
                    item.id
                    for item in open_items
                    if item.due_on is not None
                    and item.due_on < today
                    and MemoryType(item.memory_type) not in LONG_TERM_TYPES
                ],
                goals=[
                    OpenGoal(memory_id=item.id, content=item.content, last_activity=item.updated_at)
                    for item in open_items
                    if MemoryType(item.memory_type) in LONG_TERM_TYPES
                ],
                hidden=hidden,
            )
        )

    async def record_feedback(
        self, principal: Principal, key: str, kind: InsightKind, *, useful: bool
    ) -> None:
        """Remember whether an insight helped. One not useful hides it for its period."""
        async with transaction(self._session_factory) as session:
            await InsightRepository(session).record_feedback(
                principal.id, key, kind, useful=useful, now=self._clock()
            )

    async def usefulness(self) -> list[Usefulness]:
        """Across all users, per kind: the operator's measure of which insights help."""
        async with self._session_factory() as session:
            rows = await InsightRepository(session).usefulness()
        return [
            Usefulness(kind=InsightKind(kind), useful=useful, not_useful=not_useful)
            for kind, useful, not_useful in rows
        ]
