"""The SQL of insights: money notes, entity mentions, closed and open items over a window,
and the users' feedback."""

import uuid
from datetime import datetime

from sqlalchemy import Float, case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.db.base import new_uuid
from app.domain.enums import EntityStatus, EntityType, InsightKind, MemoryStatus, MemoryType
from app.models.entity import Entity
from app.models.insight_feedback import InsightFeedback
from app.models.memory import Memory
from app.models.memory_entity import MemoryEntity
from app.repositories.base import BaseRepository

_LIVE = sorted(status.value for status in (MemoryStatus.PROPOSED, MemoryStatus.ACTIVE))
# Memories that name people without saying anything about the user and them: shorthand
# next to an amount ("raju biryani"), saved links, working notes.
_NOT_ABOUT_PEOPLE = sorted(
    kind.value for kind in (MemoryType.FINANCIAL_NOTE, MemoryType.RESOURCE, MemoryType.NOTE)
)


class InsightRepository(BaseRepository):
    async def money_notes(
        self, owner_id: uuid.UUID, *, since: datetime
    ) -> list[tuple[uuid.UUID, datetime, float, str | None, str | None]]:
        """Live money notes with an amount: (id, when, amount, currency, category)."""
        financial = Memory.metadata_["financial"]
        happened = func.coalesce(Memory.observed_at, Memory.created_at)
        rows = await self._session.execute(
            select(
                Memory.id,
                happened,
                cast(financial["amount"].astext, Float),
                financial["currency"].astext,
                financial["category"].astext,
            ).where(
                Memory.owner_id == owner_id,
                Memory.status.in_(_LIVE),
                Memory.memory_type == MemoryType.FINANCIAL_NOTE.value,
                financial["amount"].astext.is_not(None),
                happened >= since,
            )
        )
        return [(row[0], row[1], float(row[2]), row[3], row[4]) for row in rows]

    async def mentions(
        self, owner_id: uuid.UUID, *, since: datetime
    ) -> list[tuple[uuid.UUID, uuid.UUID, str, str, datetime]]:
        """Live memories mentioning active entities: (memory, entity, name, type, when).
        A person counts only in memories about the user and them (``_NOT_ABOUT_PEOPLE``)."""
        happened = func.coalesce(Memory.observed_at, Memory.created_at)
        rows = await self._session.execute(
            select(Memory.id, Entity.id, Entity.canonical_name, Entity.entity_type, happened)
            .join(MemoryEntity, MemoryEntity.memory_id == Memory.id)
            .join(Entity, Entity.id == MemoryEntity.entity_id)
            .where(
                Memory.owner_id == owner_id,
                Memory.status.in_(_LIVE),
                Entity.status == EntityStatus.ACTIVE.value,
                happened >= since,
                or_(
                    Entity.entity_type != EntityType.PERSON.value,
                    Memory.memory_type.not_in(_NOT_ABOUT_PEOPLE),
                ),
            )
            .order_by(happened)
        )
        return [(row[0], row[1], row[2], row[3], row[4]) for row in rows]

    async def closures(
        self, owner_id: uuid.UUID, *, since: datetime
    ) -> list[tuple[uuid.UUID, datetime, str]]:
        rows = await self._session.execute(
            select(Memory.id, Memory.closed_at, Memory.close_reason).where(
                Memory.owner_id == owner_id,
                Memory.status.in_(_LIVE),
                Memory.closed_at.is_not(None),
                Memory.closed_at >= since,
            )
        )
        return [(row[0], row[1], row[2]) for row in rows if row[1] is not None]

    async def hidden_keys(self, user_id: uuid.UUID) -> frozenset[str]:
        rows = await self._session.scalars(
            select(InsightFeedback.insight_key).where(
                InsightFeedback.user_id == user_id, InsightFeedback.useful.is_(False)
            )
        )
        return frozenset(rows)

    async def record_feedback(
        self, user_id: uuid.UUID, key: str, kind: InsightKind, *, useful: bool, now: datetime
    ) -> None:
        statement = insert(InsightFeedback).values(
            id=new_uuid(),
            user_id=user_id,
            insight_key=key,
            kind=kind.value,
            useful=useful,
            created_at=now,
            updated_at=now,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[InsightFeedback.user_id, InsightFeedback.insight_key],
                set_={"useful": statement.excluded.useful, "updated_at": now},
            )
        )

    async def usefulness(self) -> list[tuple[str, int, int]]:
        """Per kind of insight: how many answers said useful, and how many not."""
        useful = func.count(case((InsightFeedback.useful.is_(True), 1)))
        not_useful = func.count(case((InsightFeedback.useful.is_(False), 1)))
        rows = await self._session.execute(
            select(InsightFeedback.kind, useful, not_useful)
            .group_by(InsightFeedback.kind)
            .order_by(InsightFeedback.kind)
        )
        return [(row[0], int(row[1]), int(row[2])) for row in rows]
