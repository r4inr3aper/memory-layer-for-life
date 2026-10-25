"""The people, places, and things in a user's memories, as the user sees and corrects
them.

Entity resolution decides on its own that "Priya" in two messages is one person. When it
gets that wrong, the owner fixes it here:

* Rename: the entity takes the new name; the old one is kept as a merged alias, so a
  later message using it still resolves to the same entity.
* Merge two entities that are one: everything pointing at the second (memory links,
  mentions, and entities merged into it) moves to the first, and the second becomes a
  merged alias of it.

Either way the memories that mention the entity are marked changed, so their embeddings,
which include its name, are rebuilt.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import EntityStatus, EntityType
from app.domain.errors import InvalidMemoryChangeError, RecordNotFoundError
from app.domain.memory_review import LIVE_STATUSES
from app.domain.normalization import normalize_for_matching
from app.domain.principal import Principal
from app.models.entity import Entity
from app.repositories.people_repository import PeopleRepository
from app.services.queries import MemoryView, PageResult

MAX_NAME_CHARS: Final = 200
# Memories shown on a person's page.
MAX_PERSON_MEMORIES: Final = 100


@dataclass(frozen=True, slots=True)
class PersonView:
    id: uuid.UUID
    entity_type: EntityType
    name: str
    memory_count: int
    last_seen_at: datetime | None


@dataclass(frozen=True, slots=True)
class PersonDetail:
    person: PersonView
    aliases: tuple[str, ...]
    memories: tuple[MemoryView, ...]


class PeopleService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, clock: Clock = utc_now
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def list_people(
        self,
        principal: Principal,
        *,
        entity_type: EntityType | None,
        limit: int,
        offset: int,
    ) -> PageResult[PersonView]:
        """Entities that the user's current memories mention, most mentioned first."""
        async with self._session_factory() as session:
            rows, total = await PeopleRepository(session).list_people(
                principal.id, LIVE_STATUSES, entity_type=entity_type, limit=limit, offset=offset
            )
        return PageResult(
            items=tuple(_view(row.entity, row.memory_count, row.last_seen_at) for row in rows),
            total=total,
        )

    async def get(self, principal: Principal, entity_id: uuid.UUID) -> PersonDetail:
        """An entity with its other names and the current memories that mention it. A
        merged entity answers with the one it was merged into."""
        async with self._session_factory() as session:
            people = PeopleRepository(session)
            entity = await people.surviving(principal.id, entity_id)
            if entity is None:
                raise RecordNotFoundError("Person", str(entity_id))
            memories = await people.memories_of(
                principal.id, entity.id, LIVE_STATUSES, limit=MAX_PERSON_MEMORIES
            )
            aliases = [
                alias
                for alias in await people.aliases(entity.id)
                if alias.lower() != entity.canonical_name.lower()
            ]
            last_seen = max(
                (memory.observed_at or memory.created_at for memory in memories), default=None
            )
            return PersonDetail(
                person=_view(entity, len(memories), last_seen),
                aliases=tuple(aliases),
                memories=tuple(MemoryView.of(memory) for memory in memories),
            )

    async def rename(self, principal: Principal, entity_id: uuid.UUID, name: str) -> PersonDetail:
        canonical = " ".join(name.split())
        normalized = normalize_for_matching(canonical)
        if not normalized:
            raise InvalidMemoryChangeError("A name needs some letters or digits.")
        if len(canonical) > MAX_NAME_CHARS:
            raise InvalidMemoryChangeError(f"A name can be at most {MAX_NAME_CHARS} characters.")
        now = self._clock()
        async with transaction(self._session_factory) as session:
            people = PeopleRepository(session)
            entity = await _active(people, principal, entity_id)
            if canonical == entity.canonical_name:
                raise InvalidMemoryChangeError("That is already the name.")
            if normalized != entity.normalized_name:
                # The old name stays an alias, so resolution keeps finding this entity.
                await people.add(
                    Entity(
                        id=new_uuid(),
                        entity_type=entity.entity_type,
                        canonical_name=entity.canonical_name,
                        normalized_name=entity.normalized_name,
                        status=EntityStatus.MERGED.value,
                        merged_into_id=entity.id,
                        owner_id=entity.owner_id,
                        created_at=now,
                        updated_at=now,
                    )
                )
            entity.canonical_name = canonical
            entity.normalized_name = normalized
            entity.updated_at = now
            await people.touch_memories(entity.id, now)
        return await self.get(principal, entity_id)

    async def merge(
        self, principal: Principal, entity_id: uuid.UUID, other_id: uuid.UUID
    ) -> PersonDetail:
        """Merge ``other_id`` into ``entity_id``: they are the same person or thing."""
        if entity_id == other_id:
            raise InvalidMemoryChangeError("Choose two different people.")
        now = self._clock()
        async with transaction(self._session_factory) as session:
            people = PeopleRepository(session)
            # Locked in id order, so two merges of the same pair cannot deadlock.
            first_id, second_id = sorted((entity_id, other_id), key=str)
            first = await _active(people, principal, first_id)
            second = await _active(people, principal, second_id)
            keep, other = (first, second) if first.id == entity_id else (second, first)
            await people.move_links(other.id, keep.id)
            other.status = EntityStatus.MERGED.value
            other.merged_into_id = keep.id
            other.updated_at = now
            keep.updated_at = now
            await session.flush()
            await people.touch_memories(keep.id, now)
        return await self.get(principal, entity_id)


async def _active(people: PeopleRepository, principal: Principal, entity_id: uuid.UUID) -> Entity:
    entity = await people.get_owned(principal.id, entity_id, for_update=True)
    if entity is None or entity.status != EntityStatus.ACTIVE.value:
        raise RecordNotFoundError("Person", str(entity_id))
    return entity


def _view(entity: Entity, memory_count: int, last_seen_at: datetime | None) -> PersonView:
    return PersonView(
        id=entity.id,
        entity_type=EntityType(entity.entity_type),
        name=entity.canonical_name,
        memory_count=memory_count,
        last_seen_at=last_seen_at,
    )
