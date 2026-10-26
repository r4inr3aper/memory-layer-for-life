"""The SQL of life state: the owner's open items, reminders, recently closed items, and
the claims that make each reminder and each daily brief go out once."""

import uuid
from collections.abc import Collection
from datetime import date, datetime

from sqlalchemy import ColumnElement, and_, func, or_, select, update

from app.domain.enums import EntityStatus, EntityType, MemoryState, MemoryStatus, MessageSource
from app.domain.life_state import ACTIONABLE_TYPES, LONG_TERM_TYPES
from app.models.app_user import AppUser
from app.models.entity import Entity
from app.models.memory import Memory, is_sensitive
from app.models.memory_entity import MemoryEntity
from app.models.memory_source import MemorySource
from app.models.raw_message import RawMessage
from app.repositories.base import BaseRepository

_LIVE = sorted(status.value for status in (MemoryStatus.PROPOSED, MemoryStatus.ACTIVE))


def open_item() -> ColumnElement[bool]:
    """Live memories still to act on: an actionable kind whose state is open or planned,
    or a goal or project not done, and not closed by the user."""
    state = Memory.metadata_["state"].astext
    to_do = [MemoryState.OPEN.value, MemoryState.PLANNED.value]
    return and_(
        Memory.status.in_(_LIVE),
        Memory.closed_at.is_(None),
        or_(
            and_(
                Memory.memory_type.in_(sorted(kind.value for kind in ACTIONABLE_TYPES)),
                state.in_(to_do),
            ),
            and_(
                Memory.memory_type.in_(sorted(kind.value for kind in LONG_TERM_TYPES)),
                or_(state.is_(None), state != MemoryState.DONE.value),
            ),
        ),
    )


class LifeRepository(BaseRepository):
    async def open_items(
        self, owner_id: uuid.UUID, *, include_sensitive: bool, limit: int = 500
    ) -> list[Memory]:
        """The owner's open items, soonest due first, undated ones last, oldest first."""
        conditions = [Memory.owner_id == owner_id, open_item()]
        if not include_sensitive:
            conditions.append(~is_sensitive())
        rows = await self._session.scalars(
            select(Memory)
            .where(*conditions)
            .order_by(Memory.due_on.asc().nulls_last(), Memory.created_at, Memory.id)
            .limit(limit)
        )
        return list(rows)

    async def imported(self, memory_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
        """Which of these memories rest on an imported chat (a WhatsApp export)."""
        if not memory_ids:
            return set()
        rows = await self._session.scalars(
            select(MemorySource.memory_id)
            .join(RawMessage, RawMessage.id == MemorySource.raw_message_id)
            .where(
                MemorySource.memory_id.in_(memory_ids),
                RawMessage.source == MessageSource.WHATSAPP_IMPORT.value,
            )
            .distinct()
        )
        return set(rows)

    async def count_proposed_since(self, owner_id: uuid.UUID, since: datetime) -> int:
        """The owner's memories waiting for review that were made since ``since``."""
        total = await self._session.scalar(
            select(func.count())
            .select_from(Memory)
            .where(
                Memory.owner_id == owner_id,
                Memory.status == MemoryStatus.PROPOSED.value,
                Memory.created_at >= since,
            )
        )
        return int(total or 0)

    async def reminders(
        self, owner_id: uuid.UUID, *, include_sensitive: bool, before: datetime | None = None
    ) -> list[Memory]:
        """The owner's pending reminders on live memories, soonest first."""
        conditions = [
            Memory.owner_id == owner_id,
            Memory.status.in_(_LIVE),
            Memory.remind_at.is_not(None),
        ]
        if before is not None:
            conditions.append(Memory.remind_at < before)
        if not include_sensitive:
            conditions.append(~is_sensitive())
        rows = await self._session.scalars(
            select(Memory).where(*conditions).order_by(Memory.remind_at, Memory.id)
        )
        return list(rows)

    async def recently_closed(self, owner_id: uuid.UUID, *, since: datetime) -> list[Memory]:
        rows = await self._session.scalars(
            select(Memory)
            .where(
                Memory.owner_id == owner_id,
                Memory.closed_at.is_not(None),
                Memory.closed_at >= since,
                Memory.status.in_(_LIVE),
            )
            .order_by(Memory.closed_at.desc(), Memory.id)
        )
        return list(rows)

    async def lock_due_reminders(self, now: datetime, *, limit: int) -> list[Memory]:
        """Reminders due now on live memories, locked; rows another worker holds are
        skipped, so each reminder goes out once."""
        rows = await self._session.scalars(
            select(Memory)
            .where(
                Memory.remind_at.is_not(None),
                Memory.remind_at <= now,
                Memory.status.in_(_LIVE),
                Memory.owner_id.is_not(None),
            )
            .order_by(Memory.remind_at, Memory.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        return list(rows)

    async def next_reminder_at(self) -> datetime | None:
        """When the earliest pending reminder on a live memory is due."""
        result: datetime | None = await self._session.scalar(
            select(func.min(Memory.remind_at)).where(
                Memory.remind_at.is_not(None),
                Memory.status.in_(_LIVE),
                Memory.owner_id.is_not(None),
            )
        )
        return result

    async def brief_users(self) -> list[AppUser]:
        rows = await self._session.scalars(
            select(AppUser).where(AppUser.brief_enabled.is_(True)).order_by(AppUser.id)
        )
        return list(rows)

    async def claim_brief(self, user_id: uuid.UUID, local_day: date) -> bool:
        """Record that the user's brief for this local day goes now; false when another
        worker already sent it."""
        claimed = await self._session.scalar(
            update(AppUser)
            .where(
                AppUser.id == user_id,
                AppUser.brief_enabled.is_(True),
                or_(AppUser.last_brief_on.is_(None), AppUser.last_brief_on < local_day),
            )
            .values(last_brief_on=local_day)
            .returning(AppUser.id)
        )
        return claimed is not None

    async def by_ids(self, owner_id: uuid.UUID, memory_ids: Collection[uuid.UUID]) -> list[Memory]:
        if not memory_ids:
            return []
        rows = await self._session.scalars(
            select(Memory).where(Memory.owner_id == owner_id, Memory.id.in_(memory_ids))
        )
        return list(rows)

    # --- Today (ADR-048) ---------------------------------------------------------------

    async def people_linked(self, memory_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
        """The names of the people each of these memories involves."""
        if not memory_ids:
            return {}
        rows = await self._session.execute(
            select(MemoryEntity.memory_id, Entity.canonical_name)
            .join(Entity, Entity.id == MemoryEntity.entity_id)
            .where(
                MemoryEntity.memory_id.in_(memory_ids),
                Entity.entity_type == EntityType.PERSON.value,
                Entity.status == EntityStatus.ACTIVE.value,
            )
            .order_by(Entity.canonical_name)
        )
        linked: dict[uuid.UUID, list[str]] = {}
        for memory_id, name in rows:
            linked.setdefault(memory_id, []).append(name)
        return linked

    async def people(self, owner_id: uuid.UUID) -> dict[uuid.UUID, str]:
        """The owner's people, by id."""
        rows = await self._session.execute(
            select(Entity.id, Entity.canonical_name).where(
                Entity.owner_id == owner_id,
                Entity.entity_type == EntityType.PERSON.value,
                Entity.status == EntityStatus.ACTIVE.value,
            )
        )
        return {entity_id: name for entity_id, name in rows}

    async def memories_about(
        self,
        owner_id: uuid.UUID,
        entity_ids: Collection[uuid.UUID],
        *,
        exclude: Collection[uuid.UUID],
        include_sensitive: bool,
        limit: int,
    ) -> list[Memory]:
        """The owner's newest live memories mentioning any of these entities."""
        if not entity_ids:
            return []
        conditions = [
            Memory.owner_id == owner_id,
            Memory.status.in_(_LIVE),
            Memory.id.in_(
                select(MemoryEntity.memory_id).where(MemoryEntity.entity_id.in_(entity_ids))
            ),
        ]
        if exclude:
            conditions.append(Memory.id.not_in(exclude))
        if not include_sensitive:
            conditions.append(~is_sensitive())
        rows = await self._session.scalars(
            select(Memory)
            .where(*conditions)
            .order_by(Memory.created_at.desc(), Memory.id.desc())
            .limit(limit)
        )
        return list(rows)

    async def resurfacing(
        self,
        owner_id: uuid.UUID,
        *,
        kinds: Collection[str],
        created_between: tuple[datetime, datetime],
        untouched_since: datetime,
    ) -> list[uuid.UUID]:
        """The owner's live, open memories of these kinds noted within the window and not
        touched since ``untouched_since``."""
        start, end = created_between
        rows = await self._session.scalars(
            select(Memory.id).where(
                Memory.owner_id == owner_id,
                Memory.status.in_(_LIVE),
                Memory.closed_at.is_(None),
                Memory.memory_type.in_(sorted(kinds)),
                Memory.created_at >= start,
                Memory.created_at < end,
                Memory.updated_at < untouched_since,
                Memory.metadata_["state"].astext.is_distinct_from(MemoryState.DONE.value),
            )
        )
        return list(rows)

    async def recent_proposed(
        self, owner_id: uuid.UUID, *, since: datetime, limit: int
    ) -> list[Memory]:
        """The owner's newest memories waiting for review, made since ``since``."""
        rows = await self._session.scalars(
            select(Memory)
            .where(
                Memory.owner_id == owner_id,
                Memory.status == MemoryStatus.PROPOSED.value,
                Memory.created_at >= since,
            )
            .order_by(Memory.created_at.desc(), Memory.id.desc())
            .limit(limit)
        )
        return list(rows)
