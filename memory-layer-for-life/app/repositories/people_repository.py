"""The people, places, and things in one owner's memories (entities), as the owner sees
and corrects them: listed with how many memories mention them, renamed, and merged."""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, distinct, exists, func, select, update
from sqlalchemy.orm import aliased

from app.domain.enums import EntityStatus, EntityType, MemoryStatus
from app.models.entity import Entity
from app.models.entity_mention import EntityMention
from app.models.memory import Memory
from app.models.memory_entity import MemoryEntity
from app.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class PersonRow:
    entity: Entity
    memory_count: int
    last_seen_at: datetime | None


class PeopleRepository(BaseRepository):
    async def list_people(
        self,
        owner_id: uuid.UUID,
        statuses: Collection[MemoryStatus],
        *,
        entity_type: EntityType | None,
        limit: int,
        offset: int,
    ) -> tuple[list[PersonRow], int]:
        """The owner's active entities that at least one of these memories mentions, most
        mentioned first. Returns the page and the total count."""
        live = sorted(status.value for status in statuses)
        count = func.count(distinct(Memory.id)).label("memory_count")
        last_seen = func.max(func.coalesce(Memory.observed_at, Memory.created_at))
        conditions = [Entity.owner_id == owner_id, Entity.status == EntityStatus.ACTIVE.value]
        if entity_type is not None:
            conditions.append(Entity.entity_type == entity_type.value)
        grouped = (
            select(Entity.id.label("entity_id"), count, last_seen.label("last_seen_at"))
            .join(MemoryEntity, MemoryEntity.entity_id == Entity.id)
            .join(Memory, Memory.id == MemoryEntity.memory_id)
            .where(*conditions, Memory.status.in_(live))
            .group_by(Entity.id)
            .subquery("people")
        )
        total = await self._session.scalar(select(func.count()).select_from(grouped))
        rows = await self._session.execute(
            select(Entity, grouped.c.memory_count, grouped.c.last_seen_at)
            .join(grouped, grouped.c.entity_id == Entity.id)
            .order_by(grouped.c.memory_count.desc(), func.lower(Entity.canonical_name), Entity.id)
            .limit(limit)
            .offset(offset)
        )
        return (
            [
                PersonRow(entity=row[0], memory_count=int(row[1]), last_seen_at=row[2])
                for row in rows
            ],
            int(total or 0),
        )

    async def get_owned(
        self, owner_id: uuid.UUID, entity_id: uuid.UUID, *, for_update: bool = False
    ) -> Entity | None:
        statement = select(Entity).where(Entity.id == entity_id, Entity.owner_id == owner_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.scalars(statement.execution_options(populate_existing=True))
        return result.first()

    async def surviving(self, owner_id: uuid.UUID, entity_id: uuid.UUID) -> Entity | None:
        """The entity, or the active one a merged entity ended up in. Archived entities,
        broken chains, and cycles read as missing."""
        entity = await self.get_owned(owner_id, entity_id)
        seen: set[uuid.UUID] = set()
        while entity is not None and entity.status == EntityStatus.MERGED.value:
            if entity.id in seen or entity.merged_into_id is None:
                return None
            seen.add(entity.id)
            entity = await self.get_owned(owner_id, entity.merged_into_id)
        if entity is None or entity.status != EntityStatus.ACTIVE.value:
            return None
        return entity

    async def aliases(self, entity_id: uuid.UUID) -> list[str]:
        """Other names of an entity: those of every entity merged into it, directly or
        through others, that differ from its own name."""
        chain = (
            select(Entity.id, Entity.canonical_name)
            .where(Entity.merged_into_id == entity_id)
            .cte("aliases", recursive=True)
        )
        merged = aliased(Entity)
        chain = chain.union(
            select(merged.id, merged.canonical_name).where(merged.merged_into_id == chain.c.id)
        )
        names = await self._session.scalars(select(distinct(chain.c.canonical_name)))
        return sorted(names, key=str.lower)

    async def memories_of(
        self,
        owner_id: uuid.UUID,
        entity_id: uuid.UUID,
        statuses: Collection[MemoryStatus],
        *,
        limit: int,
    ) -> list[Memory]:
        """These memories of the owner that mention the entity, newest first."""
        rows = await self._session.scalars(
            select(Memory)
            .where(
                Memory.owner_id == owner_id,
                Memory.status.in_(sorted(status.value for status in statuses)),
                exists().where(
                    MemoryEntity.memory_id == Memory.id, MemoryEntity.entity_id == entity_id
                ),
            )
            .order_by(func.coalesce(Memory.observed_at, Memory.created_at).desc(), Memory.id)
            .limit(limit)
        )
        return list(rows)

    async def add(self, entity: Entity) -> None:
        self._session.add(entity)
        await self._session.flush()

    async def move_links(self, from_entity_id: uuid.UUID, to_entity_id: uuid.UUID) -> None:
        """Point everything that refers to one entity at another: memory links (a memory
        linked to both keeps one link), mentions, and entities merged into the first."""
        target = aliased(MemoryEntity)
        await self._session.execute(
            delete(MemoryEntity)
            .where(
                MemoryEntity.entity_id == from_entity_id,
                exists().where(
                    target.memory_id == MemoryEntity.memory_id,
                    target.entity_id == to_entity_id,
                    target.relationship_type == MemoryEntity.relationship_type,
                ),
            )
            .execution_options(synchronize_session=False)
        )
        await self._session.execute(
            update(MemoryEntity)
            .where(MemoryEntity.entity_id == from_entity_id)
            .values(entity_id=to_entity_id)
            .execution_options(synchronize_session=False)
        )
        await self._session.execute(
            update(EntityMention)
            .where(EntityMention.resolved_entity_id == from_entity_id)
            .values(resolved_entity_id=to_entity_id)
            .execution_options(synchronize_session=False)
        )
        await self._session.execute(
            update(Entity)
            .where(Entity.merged_into_id == from_entity_id)
            .values(merged_into_id=to_entity_id)
            .execution_options(synchronize_session=False)
        )

    async def touch_memories(self, entity_id: uuid.UUID, now: datetime) -> None:
        """Mark the memories that mention an entity as changed, so their embeddings, which
        include its name, are rebuilt."""
        await self._session.execute(
            update(Memory)
            .where(
                Memory.id.in_(
                    select(MemoryEntity.memory_id).where(MemoryEntity.entity_id == entity_id)
                )
            )
            .values(updated_at=now)
            .execution_options(synchronize_session=False)
        )
