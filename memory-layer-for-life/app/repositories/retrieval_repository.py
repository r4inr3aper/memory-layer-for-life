"""The SQL of memory retrieval: one statement per leg, and loading results with their
evidence.

Every statement is restricted to one owner (None: the operator's own store) and to the
query's filters *before* it ranks, so a filter never empties the top of a list, and no
leg can ever see another owner's memories.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy import (
    ColumnElement,
    Float,
    and_,
    case,
    cast,
    distinct,
    exists,
    func,
    literal,
    literal_column,
    or_,
    select,
)
from sqlalchemy.orm import aliased, selectinload

from app.db.vector import cosine_distance
from app.domain.enums import EntityStatus
from app.domain.retrieval import RetrievalQuery, any_term_tsquery
from app.integrations.embeddings.base import EmbeddingSpace
from app.models.entity import Entity
from app.models.memory import Memory, is_sensitive
from app.models.memory_embedding import MemoryEmbedding
from app.models.memory_entity import MemoryEntity
from app.models.memory_source import MemorySource
from app.repositories.base import BaseRepository
from app.repositories.memory_repository import owned_by

_ENGLISH: Final[ColumnElement[str]] = literal_column("'english'::regconfig")
_SIMPLE: Final[ColumnElement[str]] = literal_column("'simple'::regconfig")
# ts_rank_cd normalization 32: rank / (rank + 1), so scores fall between 0 and 1.
_RANK_NORMALIZATION: Final = 32
# Fuzzy name matching needs some length to mean anything: "tom" is too short to be told
# apart from a typo of something else, so short names must appear exactly.
_MIN_FUZZY_NAME_LENGTH: Final = 4


@dataclass(frozen=True, slots=True)
class EntityHit:
    memory_id: uuid.UUID
    score: float
    names: tuple[str, ...]


class RetrievalRepository(BaseRepository):
    async def lexical(
        self, query: RetrievalQuery, terms: Sequence[str], *, limit: int, now: datetime
    ) -> list[tuple[uuid.UUID, float]]:
        """Memories containing any of the terms, ranked by how many and how close
        (``ts_rank_cd``). Stemmed English and the exact words both count."""
        if not terms:
            return []
        source = any_term_tsquery(terms)
        tsquery = func.to_tsquery(_ENGLISH, source).op("||")(func.to_tsquery(_SIMPLE, source))
        rank = func.ts_rank_cd(Memory.search_document, tsquery, _RANK_NORMALIZATION)
        rows = await self._session.execute(
            select(Memory.id, cast(rank, Float).label("rank"))
            .where(Memory.search_document.op("@@")(tsquery), *memory_conditions(query, now))
            .order_by(rank.desc(), Memory.created_at.desc(), Memory.id)
            .limit(limit)
        )
        return [(row[0], float(row[1])) for row in rows]

    async def semantic(
        self,
        query: RetrievalQuery,
        *,
        space: EmbeddingSpace,
        vector: Sequence[float],
        min_similarity: float,
        limit: int,
        now: datetime,
    ) -> list[tuple[uuid.UUID, float]]:
        """Memories whose embedding is nearest the query's, by cosine similarity, at
        least ``min_similarity``.

        An exact scan over the owner's embeddings in this space: exact, and fast at the
        size of one person's memories. Only embeddings at least as new as their memory
        are trusted; one the indexer has not refreshed yet is left out.
        """
        distance = cosine_distance(MemoryEmbedding.embedding, vector)
        similarity = (literal(1.0) - distance).label("similarity")
        rows = await self._session.execute(
            select(Memory.id, similarity)
            .join(MemoryEmbedding, MemoryEmbedding.memory_id == Memory.id)
            .where(
                MemoryEmbedding.embedding_space == space.key,
                MemoryEmbedding.dimensions == space.dimensions,
                MemoryEmbedding.updated_at >= Memory.updated_at,
                distance <= 1.0 - min_similarity,
                *memory_conditions(query, now),
            )
            .order_by(distance, Memory.created_at.desc(), Memory.id)
            .limit(limit)
        )
        return [(row[0], float(row[1])) for row in rows]

    async def entity(
        self,
        query: RetrievalQuery,
        *,
        query_text: str,
        min_name_similarity: float,
        limit: int,
        now: datetime,
    ) -> list[EntityHit]:
        """Memories linked to a person, place, or thing the query names.

        A name counts when it appears in the query as a phrase (PostgreSQL's word parser,
        so punctuation and scripts are handled alike), scoring 1; or, for names of four or
        more characters, when a whole word of the query is spelled close to it
        (``strict_word_similarity`` from pg_trgm, so "tom" never matches "tomorrow").
        ``query_text`` is the query normalized like entity names.
        """
        phrase = func.to_tsvector(_SIMPLE, query_text).op("@@")(
            func.phraseto_tsquery(_SIMPLE, Entity.normalized_name)
        )
        closeness = func.strict_word_similarity(Entity.normalized_name, query_text)
        fuzzy = and_(
            func.length(Entity.normalized_name) >= _MIN_FUZZY_NAME_LENGTH,
            closeness >= min_name_similarity,
        )
        match = case((phrase, literal(1.0)), else_=cast(closeness, Float))
        score = func.max(match).label("score")
        rows = await self._session.execute(
            select(Memory.id, score, func.array_agg(distinct(Entity.canonical_name)))
            .join(MemoryEntity, MemoryEntity.memory_id == Memory.id)
            .join(Entity, Entity.id == MemoryEntity.entity_id)
            .where(
                owned_by(Entity.owner_id, query.owner_id),
                Entity.status.in_([EntityStatus.ACTIVE.value, EntityStatus.MERGED.value]),
                or_(phrase, fuzzy),
                *memory_conditions(query, now),
            )
            .group_by(Memory.id, Memory.created_at)
            .order_by(score.desc(), Memory.created_at.desc(), Memory.id)
            .limit(limit)
        )
        return [
            EntityHit(memory_id=row[0], score=float(row[1]), names=tuple(sorted(row[2] or ())))
            for row in rows
        ]

    async def load(
        self, owner_id: uuid.UUID | None, memory_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, Memory]:
        """The memories with their evidence and entities. Restricted to the owner again,
        so a mistake upstream can never leak another owner's memory."""
        if not memory_ids:
            return {}
        memories = await self._session.scalars(
            select(Memory)
            .where(Memory.id.in_(memory_ids), owned_by(Memory.owner_id, owner_id))
            .options(
                selectinload(Memory.sources).joinedload(MemorySource.raw_message),
                selectinload(Memory.memory_entities).joinedload(MemoryEntity.entity),
            )
        )
        return {memory.id: memory for memory in memories}


def memory_conditions(query: RetrievalQuery, now: datetime) -> list[ColumnElement[bool]]:
    """The restrictions every leg applies: the owner, and the query's filters."""
    filters = query.filters
    conditions: list[ColumnElement[bool]] = [
        owned_by(Memory.owner_id, query.owner_id),
        Memory.status.in_(sorted(status.value for status in filters.statuses)),
    ]
    if filters.memory_types is not None:
        conditions.append(
            Memory.memory_type.in_(sorted(kind.value for kind in filters.memory_types))
        )
    happened = func.coalesce(Memory.observed_at, Memory.created_at)
    if filters.observed_from is not None:
        conditions.append(happened >= filters.observed_from)
    if filters.observed_to is not None:
        conditions.append(happened < filters.observed_to)
    if not filters.include_expired:
        conditions.append(or_(Memory.valid_until.is_(None), Memory.valid_until > now))
    if not filters.include_superseded:
        newer = aliased(Memory)
        conditions.append(~exists().where(newer.supersedes_memory_id == Memory.id))
    if not filters.include_sensitive:
        conditions.append(~is_sensitive())
    return conditions
