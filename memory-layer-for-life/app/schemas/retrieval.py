"""Requests and responses of memory search."""

import uuid
from datetime import datetime

from pydantic import AwareDatetime, Field

from app.domain.enums import EntityType, MemoryType, MessageSource, RetrievalLeg, SourceRole
from app.domain.retrieval import MAX_QUERY_CHARS
from app.schemas.common import ResponseSchema, StrictSchema
from app.schemas.memory import MemoryResponse

MAX_SEARCH_RESULTS = 25


class MemorySearchRequest(StrictSchema):
    """A question to the memory store. Sent in the body, never in the URL, because a
    query can be as private as the memories it searches."""

    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    limit: int = Field(default=10, ge=1, le=MAX_SEARCH_RESULTS)
    memory_types: list[MemoryType] | None = Field(
        default=None, min_length=1, description="Only these kinds of memory."
    )
    observed_from: AwareDatetime | None = Field(
        default=None, description="Only memories of things that happened from then on."
    )
    observed_to: AwareDatetime | None = Field(
        default=None, description="Only memories of things that happened before then."
    )
    include_superseded: bool = Field(
        default=False, description="Also memories a later one replaced."
    )
    include_expired: bool = Field(
        default=False, description="Also memories whose validity has ended."
    )


class MemorySearchMatch(ResponseSchema):
    """How one leg found the memory: its rank there, and that leg's own score (a text
    rank, a cosine similarity, or a name match from 0 to 1)."""

    leg: RetrievalLeg
    rank: int
    score: float


class MemorySearchSource(ResponseSchema):
    raw_message_id: uuid.UUID
    role: SourceRole
    source: MessageSource
    sent_at: datetime | None
    evidence: str | None = Field(description="The part of the message the memory rests on.")
    content: str = Field(description="The message, cut to 500 characters.")


class MemorySearchEntity(ResponseSchema):
    entity_id: uuid.UUID
    entity_type: EntityType
    name: str


class MemorySearchHit(ResponseSchema):
    memory: MemoryResponse
    rank: int
    score: float = Field(description="Fused score; compare within one search only.")
    rerank_score: float | None
    matched_by: list[MemorySearchMatch]
    matched_names: list[str] = Field(description="Names in the query linked to this memory.")
    sources: list[MemorySearchSource]
    entities: list[MemorySearchEntity]


class MemorySearchLeg(ResponseSchema):
    leg: str
    used: bool
    candidates: int
    duration_ms: int
    error: str | None = Field(description="Why the leg was skipped; the search went on.")


class MemorySearchResponse(ResponseSchema):
    """The memories that bear on the query, most relevant first. Relevance is not truth:
    each memory comes with the messages it rests on and its review status."""

    query: str
    items: list[MemorySearchHit]
    legs: list[MemorySearchLeg]
    embedding_space: str | None
    reranked: bool
    degraded: bool = Field(description="True when a leg or the reranker was unavailable.")
    duration_ms: int
