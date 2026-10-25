import uuid
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.orm import InstrumentedAttribute, selectinload

from app.db.base import new_uuid
from app.domain.enums import MemoryEventAction, MemoryStatus, MemoryType, RelationType
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from app.models.memory_entity import MemoryEntity
from app.models.memory_event import MemoryEvent
from app.models.memory_relation import MemoryRelation
from app.models.memory_source import MemorySource
from app.repositories.base import BaseRepository


class MemoryRepository(BaseRepository):
    """Persistence of memories, their provenance, their entity links, and their change
    history."""

    async def get_with_provenance(
        self, memory_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
    ) -> Memory | None:
        """Load one of the owner's memories together with its sources, their messages,
        and its entities. None is the operator's store."""
        result = await self._session.scalars(
            select(Memory)
            .where(Memory.id == memory_id, owned_by(Memory.owner_id, owner_id))
            .options(
                selectinload(Memory.sources).joinedload(MemorySource.raw_message),
                selectinload(Memory.sources).joinedload(MemorySource.extraction_result),
                selectinload(Memory.memory_entities).joinedload(MemoryEntity.entity),
            )
            .execution_options(populate_existing=True)
        )
        return result.first()

    async def get_owned(
        self, memory_id: uuid.UUID, owner_id: uuid.UUID | None, *, for_update: bool = False
    ) -> Memory | None:
        """One of the owner's memories, optionally locked until the transaction ends."""
        statement = select(Memory).where(
            Memory.id == memory_id, owned_by(Memory.owner_id, owner_id)
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.scalars(statement.execution_options(populate_existing=True))
        return result.first()

    async def lock_owned(
        self, memory_ids: Collection[uuid.UUID], owner_id: uuid.UUID | None
    ) -> dict[uuid.UUID, Memory]:
        """Several of the owner's memories, locked in id order so two changes touching
        the same memories cannot deadlock. Ids that are not the owner's are missing."""
        if not memory_ids:
            return {}
        rows = await self._session.scalars(
            select(Memory)
            .where(Memory.id.in_(memory_ids), owned_by(Memory.owner_id, owner_id))
            .order_by(Memory.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return {memory.id: memory for memory in rows}

    async def get_many(self, memory_ids: Collection[uuid.UUID]) -> list[Memory]:
        if not memory_ids:
            return []
        rows = await self._session.scalars(select(Memory).where(Memory.id.in_(memory_ids)))
        return list(rows)

    async def ids_for_extraction_result(self, extraction_result_id: uuid.UUID) -> list[uuid.UUID]:
        rows = await self._session.scalars(
            select(Memory.id)
            .where(Memory.origin_extraction_result_id == extraction_result_id)
            .order_by(Memory.origin_ordinal)
        )
        return list(rows)

    async def list_memories(
        self,
        *,
        status: MemoryStatus | None = None,
        memory_type: MemoryType | None = None,
        processing_run_id: uuid.UUID | None = None,
        owner_id: uuid.UUID | None = None,
        statuses: Collection[MemoryStatus] | None = None,
        oldest_first: bool = False,
        limit: int,
        offset: int,
    ) -> tuple[list[Memory], int]:
        """Page through the owner's memories, newest first (None: the operator's store).
        ``status`` keeps one status, ``statuses`` any of several. Returns the page and the
        total count."""
        conditions = [owned_by(Memory.owner_id, owner_id)]
        if status is not None:
            conditions.append(Memory.status == status.value)
        if statuses is not None:
            conditions.append(Memory.status.in_(sorted(value.value for value in statuses)))
        if memory_type is not None:
            conditions.append(Memory.memory_type == memory_type.value)
        if processing_run_id is not None:
            conditions.append(
                Memory.origin_extraction_result_id.in_(
                    select(ExtractionResult.id).where(
                        ExtractionResult.processing_run_id == processing_run_id
                    )
                )
            )
        total = await self._session.scalar(
            select(func.count()).select_from(Memory).where(*conditions)
        )
        order = (
            (Memory.created_at, Memory.id)
            if oldest_first
            else (Memory.created_at.desc(), Memory.id.desc())
        )
        rows = await self._session.scalars(
            select(Memory).where(*conditions).order_by(*order).limit(limit).offset(offset)
        )
        return list(rows), int(total or 0)

    async def count(self, owner_id: uuid.UUID | None, status: MemoryStatus) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(Memory)
            .where(owned_by(Memory.owner_id, owner_id), Memory.status == status.value)
        )
        return int(total or 0)

    async def add_memories(self, memories: Sequence[Memory]) -> None:
        self._session.add_all(memories)
        await self._session.flush()

    async def add_sources(self, sources: Sequence[MemorySource]) -> None:
        self._session.add_all(sources)
        await self._session.flush()

    async def add_entity_links(self, links: Sequence[MemoryEntity]) -> None:
        self._session.add_all(links)
        await self._session.flush()

    async def copy_provenance(
        self, from_memory_id: uuid.UUID, to_memory_id: uuid.UUID, *, now: datetime
    ) -> None:
        """Give one memory the evidence and entity links of another, skipping those it
        already has. The other keeps its own."""
        sources = await self._session.scalars(
            select(MemorySource).where(MemorySource.memory_id.in_([from_memory_id, to_memory_id]))
        )
        own_sources, their_sources = _split(list(sources), to_memory_id)
        held = {(source.raw_message_id, source.extraction_result_id) for source in own_sources}
        for source in their_sources:
            key = (source.raw_message_id, source.extraction_result_id)
            if key in held:
                continue
            held.add(key)
            self._session.add(
                MemorySource(
                    id=new_uuid(),
                    memory_id=to_memory_id,
                    raw_message_id=source.raw_message_id,
                    extraction_result_id=source.extraction_result_id,
                    evidence_text=source.evidence_text,
                    source_role=source.source_role,
                    created_at=now,
                )
            )

        links = await self._session.scalars(
            select(MemoryEntity).where(MemoryEntity.memory_id.in_([from_memory_id, to_memory_id]))
        )
        own_links, their_links = _split(list(links), to_memory_id)
        linked = {(link.entity_id, link.relationship_type) for link in own_links}
        for link in their_links:
            link_key = (link.entity_id, link.relationship_type)
            if link_key in linked:
                continue
            linked.add(link_key)
            self._session.add(
                MemoryEntity(
                    memory_id=to_memory_id,
                    entity_id=link.entity_id,
                    relationship_type=link.relationship_type,
                    created_at=now,
                )
            )
        await self._session.flush()

    # --- Versions and relations ----------------------------------------------------

    async def add_relation(
        self,
        source_memory_id: uuid.UUID,
        target_memory_id: uuid.UUID,
        relation_type: RelationType,
        *,
        now: datetime,
    ) -> None:
        self._session.add(
            MemoryRelation(
                id=new_uuid(),
                source_memory_id=source_memory_id,
                target_memory_id=target_memory_id,
                relation_type=relation_type.value,
                created_at=now,
            )
        )
        await self._session.flush()

    async def replaced_by(self, memory_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
        """The memories these ones replaced: their older versions (``supersedes_memory_id``)
        and memories merged into or replaced by them (``supersedes`` relations)."""
        if not memory_ids:
            return set()
        versions = await self._session.scalars(
            select(Memory.supersedes_memory_id).where(
                Memory.id.in_(memory_ids), Memory.supersedes_memory_id.is_not(None)
            )
        )
        replaced = await self._session.scalars(
            select(MemoryRelation.target_memory_id).where(
                MemoryRelation.source_memory_id.in_(memory_ids),
                MemoryRelation.relation_type == RelationType.SUPERSEDES.value,
            )
        )
        return {memory_id for memory_id in [*versions, *replaced] if memory_id is not None}

    async def successor_of(self, memory_id: uuid.UUID) -> uuid.UUID | None:
        """The memory that replaced this one: its newer version, or the memory it was
        merged into or replaced by."""
        newer: uuid.UUID | None = await self._session.scalar(
            select(Memory.id).where(Memory.supersedes_memory_id == memory_id).limit(1)
        )
        if newer is not None:
            return newer
        survivor: uuid.UUID | None = await self._session.scalar(
            select(MemoryRelation.source_memory_id)
            .where(
                MemoryRelation.target_memory_id == memory_id,
                MemoryRelation.relation_type == RelationType.SUPERSEDES.value,
            )
            .order_by(MemoryRelation.created_at.desc())
            .limit(1)
        )
        return survivor

    async def delete_memories(self, memory_ids: Collection[uuid.UUID]) -> None:
        """Delete memories with their links and provenance; their history and embeddings
        go with them (cascade). A memory that superseded one of them is unlinked."""
        if not memory_ids:
            return
        ids = list(memory_ids)
        await self._session.execute(
            delete(MemoryRelation).where(
                or_(
                    MemoryRelation.source_memory_id.in_(ids),
                    MemoryRelation.target_memory_id.in_(ids),
                )
            )
        )
        await self._session.execute(delete(MemoryEntity).where(MemoryEntity.memory_id.in_(ids)))
        await self._session.execute(delete(MemorySource).where(MemorySource.memory_id.in_(ids)))
        await self._session.execute(
            update(Memory)
            .where(Memory.supersedes_memory_id.in_(ids))
            .values(supersedes_memory_id=None)
            .execution_options(synchronize_session=False)
        )
        await self._session.execute(
            delete(Memory).where(Memory.id.in_(ids)).execution_options(synchronize_session=False)
        )

    # --- History -------------------------------------------------------------------

    async def add_event(
        self,
        memory_id: uuid.UUID,
        action: MemoryEventAction,
        *,
        now: datetime,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self._session.add(
            MemoryEvent(
                id=new_uuid(),
                memory_id=memory_id,
                action=action.value,
                details=dict(details or {}),
                created_at=now,
            )
        )
        await self._session.flush()

    async def events(self, memory_id: uuid.UUID) -> list[MemoryEvent]:
        """A memory's history, oldest first. Ids are time-ordered and break ties."""
        rows = await self._session.scalars(
            select(MemoryEvent)
            .where(MemoryEvent.memory_id == memory_id)
            .order_by(MemoryEvent.created_at, MemoryEvent.id)
        )
        return list(rows)

    async def events_for_owner(self, owner_id: uuid.UUID) -> list[MemoryEvent]:
        """Every history entry of the owner's memories, oldest first, for an export."""
        rows = await self._session.scalars(
            select(MemoryEvent)
            .join(Memory, Memory.id == MemoryEvent.memory_id)
            .where(Memory.owner_id == owner_id)
            .order_by(MemoryEvent.created_at, MemoryEvent.id)
        )
        return list(rows)

    async def dismissed_pairs(self, owner_id: uuid.UUID) -> set[frozenset[uuid.UUID]]:
        """Pairs of the owner's memories whose suggestion was dismissed."""
        rows = await self._session.execute(
            select(MemoryEvent.memory_id, MemoryEvent.details["other_memory_id"].astext)
            .join(Memory, Memory.id == MemoryEvent.memory_id)
            .where(
                Memory.owner_id == owner_id,
                MemoryEvent.action == MemoryEventAction.SUGGESTION_DISMISSED.value,
            )
        )
        return {frozenset({memory_id, uuid.UUID(other)}) for memory_id, other in rows if other}


def owned_by(
    column: InstrumentedAttribute[uuid.UUID | None], owner_id: uuid.UUID | None
) -> ColumnElement[bool]:
    """Rows of one owner; None selects the operator's own rows, never everyone's."""
    return column.is_(None) if owner_id is None else column == owner_id


def _split[RowT: (MemorySource, MemoryEntity)](
    rows: list[RowT], memory_id: uuid.UUID
) -> tuple[list[RowT], list[RowT]]:
    """Rows of ``memory_id``, and the others."""
    own = [row for row in rows if row.memory_id == memory_id]
    return own, [row for row in rows if row.memory_id != memory_id]
