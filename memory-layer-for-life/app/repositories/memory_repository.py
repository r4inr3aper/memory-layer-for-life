import uuid
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Float, cast, delete, false, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import InstrumentedAttribute, selectinload

from app.db.base import new_uuid
from app.domain.enums import (
    MemoryEntityRelation,
    MemoryEventAction,
    MemoryOrigin,
    MemoryStatus,
    MemoryType,
    MessageSource,
    RelationType,
    SourceRole,
)
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from app.models.memory_entity import MemoryEntity
from app.models.memory_event import MemoryEvent
from app.models.memory_relation import MemoryRelation
from app.models.memory_source import MemorySource
from app.models.raw_message import RawMessage
from app.repositories.base import BaseRepository

_LIVE = sorted(status.value for status in (MemoryStatus.PROPOSED, MemoryStatus.ACTIVE))


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

    async def add_entity_links_if_absent(
        self, memory_id: uuid.UUID, entity_ids: Collection[uuid.UUID], *, now: datetime
    ) -> None:
        """Link a memory to entities it mentions, skipping links it already has."""
        if not entity_ids:
            return
        await self._session.execute(
            insert(MemoryEntity)
            .values(
                [
                    {
                        "memory_id": memory_id,
                        "entity_id": entity_id,
                        "relationship_type": MemoryEntityRelation.MENTIONS.value,
                        "created_at": now,
                    }
                    for entity_id in entity_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["memory_id", "entity_id", "relationship_type"])
        )

    # --- Reconciliation (ADR-048) --------------------------------------------------

    async def same_memory_candidates(
        self,
        owner_id: uuid.UUID,
        *,
        memory_type: MemoryType,
        normalized_content: str,
        links: Collection[str],
        min_similarity: float,
        limit: int = 5,
    ) -> list[tuple[Memory, float, bool]]:
        """The owner's live, open memories of one kind that may say what a new one says:
        text at least ``min_similarity`` alike (pg_trgm), or naming one of ``links``. Most
        alike first, each with its similarity and whether it names one of the links."""
        similarity = cast(
            func.coalesce(func.similarity(Memory.normalized_content, normalized_content), 0.0),
            Float,
        )
        shares_link: ColumnElement[bool] = (
            or_(*(Memory.content.icontains(link, autoescape=True) for link in sorted(links)))
            if links
            else false()
        )
        rows = await self._session.execute(
            select(Memory, similarity, shares_link)
            .where(
                Memory.owner_id == owner_id,
                Memory.memory_type == memory_type.value,
                Memory.status.in_(_LIVE),
                Memory.closed_at.is_(None),
                or_(similarity >= min_similarity, shares_link),
            )
            .order_by(similarity.desc(), Memory.created_at.desc())
            .limit(limit)
        )
        return [(row[0], float(row[1]), bool(row[2])) for row in rows]

    async def saved_from_chat_messages(
        self, owner_id: uuid.UUID, message_ids: Collection[uuid.UUID]
    ) -> list[tuple[str, Memory]]:
        """The owner's live memories that quote these chat messages, as (chat message id,
        memory), oldest memory first."""
        if not message_ids:
            return []
        rows = await self._session.execute(
            select(RawMessage.source_message_id, Memory)
            .join(MemorySource, MemorySource.raw_message_id == RawMessage.id)
            .join(Memory, Memory.id == MemorySource.memory_id)
            .where(
                RawMessage.owner_id == owner_id,
                RawMessage.source == MessageSource.APP_CHAT.value,
                RawMessage.source_message_id.in_(sorted(str(item) for item in message_ids)),
                MemorySource.source_role == SourceRole.SUPPORTING.value,
                Memory.owner_id == owner_id,
                Memory.status.in_(_LIVE),
            )
            .order_by(Memory.created_at, Memory.id)
        )
        return [(str(row[0]), row[1]) for row in rows]

    async def saved_by_assistant_since(
        self, owner_id: uuid.UUID, since: datetime, *, limit: int = 10
    ) -> list[Memory]:
        """Memories the assistant wrote for the owner since ``since`` (reminders), oldest
        first. Sensitive ones are left out: this goes to a model."""
        rows = await self._session.scalars(
            select(Memory)
            .where(
                Memory.owner_id == owner_id,
                Memory.created_by == MemoryOrigin.ASSISTANT.value,
                Memory.created_at >= since,
                Memory.status.in_(_LIVE),
                Memory.metadata_["sensitivity"].astext.is_distinct_from("sensitive"),
            )
            .order_by(Memory.created_at, Memory.id)
            .limit(limit)
        )
        return list(rows)

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
