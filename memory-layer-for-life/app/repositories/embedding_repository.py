import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, delete, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from app.db.base import new_uuid
from app.db.vector import Vector
from app.integrations.embeddings.base import EmbeddingSpace
from app.models.entity import Entity
from app.models.memory import Memory, is_sensitive
from app.models.memory_embedding import MemoryEmbedding
from app.models.memory_entity import MemoryEntity
from app.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class IndexCandidate:
    """A memory as the indexer needs it, with what its embedding in the space was made
    from (None when it has none)."""

    memory_id: uuid.UUID
    owner_id: uuid.UUID | None
    memory_type: str
    content: str
    entity_names: tuple[str, ...]
    stored_sha256: str | None
    stored_document_version: str | None


class EmbeddingRepository(BaseRepository):
    """Persistence of memory embeddings, the derived index retrieval searches."""

    async def candidates(
        self,
        space: EmbeddingSpace,
        *,
        after: uuid.UUID | None,
        limit: int,
        changed_only: bool,
    ) -> list[IndexCandidate]:
        """Memories to look at, in id order after ``after`` (keyset paging, so a pass
        ends even while memories are added).

        ``changed_only`` keeps those that have no embedding in the space or changed since
        they were embedded; without it every memory is a candidate, for a full check.
        Sensitive memories are never candidates: their text is not sent to the provider.
        """
        stored = aliased(MemoryEmbedding)
        statement = (
            select(
                Memory.id,
                Memory.owner_id,
                Memory.memory_type,
                Memory.content,
                stored.content_sha256,
                stored.document_version,
            )
            .outerjoin(
                stored,
                (stored.memory_id == Memory.id) & (stored.embedding_space == space.key),
            )
            .where(~is_sensitive())
            .order_by(Memory.id)
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(Memory.id > after)
        if changed_only:
            statement = statement.where(
                or_(stored.id.is_(None), Memory.updated_at > stored.updated_at)
            )
        rows = (await self._session.execute(statement)).all()
        names = await self._entity_names([row[0] for row in rows])
        return [
            IndexCandidate(
                memory_id=row[0],
                owner_id=row[1],
                memory_type=row[2],
                content=row[3],
                entity_names=names.get(row[0], ()),
                stored_sha256=row[4],
                stored_document_version=row[5],
            )
            for row in rows
        ]

    async def _entity_names(
        self, memory_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[str, ...]]:
        if not memory_ids:
            return {}
        rows = await self._session.execute(
            select(MemoryEntity.memory_id, Entity.canonical_name)
            .join(Entity, Entity.id == MemoryEntity.entity_id)
            .where(MemoryEntity.memory_id.in_(memory_ids))
        )
        names: dict[uuid.UUID, list[str]] = defaultdict(list)
        for memory_id, name in rows:
            names[memory_id].append(name)
        return {memory_id: tuple(sorted(values)) for memory_id, values in names.items()}

    async def upsert(
        self,
        *,
        memory_id: uuid.UUID,
        space: EmbeddingSpace,
        vector: Sequence[float],
        content_sha256: str,
        document_version: str,
        now: datetime,
    ) -> None:
        """Store the memory's embedding in the space, replacing an older one."""
        statement = insert(MemoryEmbedding).from_select(
            [
                MemoryEmbedding.id,
                MemoryEmbedding.memory_id,
                MemoryEmbedding.embedding_space,
                MemoryEmbedding.dimensions,
                MemoryEmbedding.embedding,
                MemoryEmbedding.content_sha256,
                MemoryEmbedding.document_version,
                MemoryEmbedding.created_at,
                MemoryEmbedding.updated_at,
            ],
            # Selected from the memory, so a memory deleted meanwhile inserts nothing.
            select(
                literal(new_uuid(), PG_UUID(as_uuid=True)),
                Memory.id,
                literal(space.key, String()),
                literal(space.dimensions, Integer()),
                literal(list(vector), Vector()),
                literal(content_sha256, String()),
                literal(document_version, String()),
                literal(now, DateTime(timezone=True)),
                literal(now, DateTime(timezone=True)),
            ).where(Memory.id == memory_id),
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[MemoryEmbedding.memory_id, MemoryEmbedding.embedding_space],
                set_={
                    "dimensions": statement.excluded.dimensions,
                    "embedding": statement.excluded.embedding,
                    "content_sha256": statement.excluded.content_sha256,
                    "document_version": statement.excluded.document_version,
                    "updated_at": statement.excluded.updated_at,
                },
            )
        )

    async def mark_current(
        self, memory_ids: Sequence[uuid.UUID], space: EmbeddingSpace, *, now: datetime
    ) -> None:
        """Record that these embeddings were checked against their memory and still
        match it, so they stop being candidates."""
        if not memory_ids:
            return
        await self._session.execute(
            update(MemoryEmbedding)
            .where(
                MemoryEmbedding.memory_id.in_(memory_ids),
                MemoryEmbedding.embedding_space == space.key,
            )
            .values(updated_at=now)
        )

    async def delete_for(self, memory_id: uuid.UUID) -> None:
        """Remove a memory's embeddings in every space, for one marked sensitive."""
        await self._session.execute(
            delete(MemoryEmbedding).where(MemoryEmbedding.memory_id == memory_id)
        )

    async def delete_other_spaces(self, space: EmbeddingSpace) -> int:
        """Remove embeddings of every other space, for example after a model change."""
        result = await self._session.execute(
            delete(MemoryEmbedding).where(MemoryEmbedding.embedding_space != space.key)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def coverage(self, space: EmbeddingSpace) -> tuple[int, int]:
        """How many memories have a current embedding in the space, out of all that
        can have one (sensitive memories cannot)."""
        total = await self._session.scalar(
            select(func.count()).select_from(Memory).where(~is_sensitive())
        )
        embedded = await self._session.scalar(
            select(func.count())
            .select_from(MemoryEmbedding)
            .join(Memory, Memory.id == MemoryEmbedding.memory_id)
            .where(
                MemoryEmbedding.embedding_space == space.key,
                MemoryEmbedding.updated_at >= Memory.updated_at,
            )
        )
        return int(embedded or 0), int(total or 0)
