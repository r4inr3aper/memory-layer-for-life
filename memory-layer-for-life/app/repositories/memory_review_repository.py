"""The SQL of memory review: pairs of one owner's memories that look alike, and what is
known about each pair.

Text similarity is pg_trgm's ``similarity`` over ``normalized_content``; the self-join uses
the ``%`` operator so the trigram index finds candidates without comparing every pair.
Meaning similarity compares current embeddings in one space, nearest neighbours of the
owner's most recent memories only, so the scan stays bounded however long the history.
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import Float, and_, case, column, distinct, func, literal, select, values
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import aliased

from app.domain.enums import MemoryStatus
from app.integrations.embeddings.base import EmbeddingSpace
from app.models.memory import Memory
from app.models.memory_embedding import MemoryEmbedding
from app.models.memory_entity import MemoryEntity
from app.repositories.base import BaseRepository

# Nearest neighbours looked up for each recent memory.
_NEIGHBOURS: Final = 3


@dataclass(frozen=True, slots=True)
class PairRow:
    """Two memories, ``first_id < second_id``, with what is known about them together."""

    first_id: uuid.UUID
    second_id: uuid.UUID
    same_type: bool
    identical_text: bool
    text_similarity: float
    meaning_similarity: float | None
    shared_entities: int


class MemoryReviewRepository(BaseRepository):
    async def alike_by_text(
        self,
        owner_id: uuid.UUID,
        statuses: Collection[MemoryStatus],
        *,
        min_similarity: float,
        limit: int,
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        """Pairs of the owner's memories whose text is at least this similar, most
        similar first."""
        # The threshold of the % operator, for this transaction only.
        await self._session.execute(
            select(func.set_config("pg_trgm.similarity_threshold", str(min_similarity), True))
        )
        first = aliased(Memory)
        second = aliased(Memory)
        similarity = func.similarity(first.normalized_content, second.normalized_content)
        live = sorted(status.value for status in statuses)
        rows = await self._session.execute(
            select(first.id, second.id)
            .join(
                second,
                and_(
                    second.owner_id == first.owner_id,
                    second.id > first.id,
                    first.normalized_content.op("%")(second.normalized_content),
                ),
            )
            .where(first.owner_id == owner_id, first.status.in_(live), second.status.in_(live))
            .order_by(similarity.desc(), first.id, second.id)
            .limit(limit)
        )
        return [(row[0], row[1]) for row in rows]

    async def alike_by_meaning(
        self,
        owner_id: uuid.UUID,
        statuses: Collection[MemoryStatus],
        *,
        space: EmbeddingSpace,
        min_similarity: float,
        recent: int,
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        """Pairs among the owner's ``recent`` newest memories and their nearest
        neighbours, at least this close in meaning. Only current embeddings count."""
        live = sorted(status.value for status in statuses)
        anchor_memory = aliased(Memory)
        anchor_embedding = aliased(MemoryEmbedding)
        anchors = (
            select(anchor_memory.id.label("memory_id"), anchor_embedding.embedding)
            .join(anchor_embedding, anchor_embedding.memory_id == anchor_memory.id)
            .where(
                anchor_memory.owner_id == owner_id,
                anchor_memory.status.in_(live),
                anchor_embedding.embedding_space == space.key,
                anchor_embedding.dimensions == space.dimensions,
                anchor_embedding.updated_at >= anchor_memory.updated_at,
            )
            .order_by(anchor_memory.created_at.desc())
            .limit(recent)
            .subquery("anchors")
        )
        neighbour_memory = aliased(Memory)
        neighbour_embedding = aliased(MemoryEmbedding)
        distance = neighbour_embedding.embedding.op("<=>", return_type=Float)(anchors.c.embedding)
        neighbours = (
            select(neighbour_memory.id.label("memory_id"), distance.label("distance"))
            .join(neighbour_embedding, neighbour_embedding.memory_id == neighbour_memory.id)
            .where(
                neighbour_memory.owner_id == owner_id,
                neighbour_memory.status.in_(live),
                neighbour_memory.id != anchors.c.memory_id,
                neighbour_embedding.embedding_space == space.key,
                neighbour_embedding.dimensions == space.dimensions,
                neighbour_embedding.updated_at >= neighbour_memory.updated_at,
            )
            .order_by(distance)
            .limit(_NEIGHBOURS)
            .lateral("neighbours")
        )
        rows = await self._session.execute(
            select(anchors.c.memory_id, neighbours.c.memory_id)
            .select_from(anchors)
            .join(neighbours, literal(True))
            .where(neighbours.c.distance <= 1.0 - min_similarity)
        )
        pairs = {
            (min(first, second, key=str), max(first, second, key=str)) for first, second in rows
        }
        return sorted(pairs, key=lambda pair: (str(pair[0]), str(pair[1])))

    async def pair_signals(
        self,
        pairs: Sequence[tuple[uuid.UUID, uuid.UUID]],
        *,
        space: EmbeddingSpace | None,
    ) -> list[PairRow]:
        """Everything ``classify`` needs about each pair, in one statement."""
        if not pairs:
            return []
        ordered = sorted({_ordered(first, second) for first, second in pairs})
        pair_table = (
            values(
                column("first_id", PG_UUID(as_uuid=True)),
                column("second_id", PG_UUID(as_uuid=True)),
                name="pairs",
            )
            .data(ordered)
            .alias("pairs")
        )
        first = aliased(Memory)
        second = aliased(Memory)
        first_link = aliased(MemoryEntity)
        second_link = aliased(MemoryEntity)
        shared = (
            select(func.count(distinct(first_link.entity_id)))
            .join(second_link, second_link.entity_id == first_link.entity_id)
            .where(first_link.memory_id == first.id, second_link.memory_id == second.id)
            .scalar_subquery()
        )
        columns: list[Any] = [
            first.id,
            second.id,
            first.memory_type == second.memory_type,
            first.normalized_content == second.normalized_content,
            func.coalesce(
                func.similarity(first.normalized_content, second.normalized_content), 0.0
            ),
            shared,
        ]
        statement = (
            select(*columns)
            .select_from(pair_table)
            .join(first, first.id == pair_table.c.first_id)
            .join(second, second.id == pair_table.c.second_id)
        )
        if space is not None:
            first_vector = aliased(MemoryEmbedding)
            second_vector = aliased(MemoryEmbedding)
            meaning = case(
                (
                    and_(first_vector.id.is_not(None), second_vector.id.is_not(None)),
                    literal(1.0)
                    - first_vector.embedding.op("<=>", return_type=Float)(second_vector.embedding),
                ),
                else_=None,
            )
            statement = (
                statement.add_columns(meaning)
                .outerjoin(
                    first_vector,
                    and_(
                        first_vector.memory_id == first.id,
                        first_vector.embedding_space == space.key,
                        first_vector.dimensions == space.dimensions,
                        first_vector.updated_at >= first.updated_at,
                    ),
                )
                .outerjoin(
                    second_vector,
                    and_(
                        second_vector.memory_id == second.id,
                        second_vector.embedding_space == space.key,
                        second_vector.dimensions == space.dimensions,
                        second_vector.updated_at >= second.updated_at,
                    ),
                )
            )
        rows = await self._session.execute(statement)
        return [
            PairRow(
                first_id=row[0],
                second_id=row[1],
                same_type=bool(row[2]),
                identical_text=bool(row[3]),
                text_similarity=float(row[4]),
                shared_entities=int(row[5] or 0),
                meaning_similarity=(
                    float(row[6]) if space is not None and row[6] is not None else None
                ),
            )
            for row in rows
        ]


def _ordered(first: uuid.UUID, second: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """A pair in one canonical order, so each pair is considered once."""
    return (first, second) if str(first) < str(second) else (second, first)
