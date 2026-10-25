"""Between memory search's HTTP shapes and the retrieval engine."""

import uuid

from app.api.v1.mappers import to_memory_response
from app.domain.retrieval import RetrievalFilters, RetrievalQuery
from app.schemas.retrieval import (
    MemorySearchEntity,
    MemorySearchHit,
    MemorySearchLeg,
    MemorySearchMatch,
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchSource,
)
from app.services.retrieval.engine import RetrievalResult


def to_retrieval_query(request: MemorySearchRequest, owner_id: uuid.UUID | None) -> RetrievalQuery:
    """A search people make for themselves, so sensitive memories are included (and
    marked). Raises ``InvalidRetrievalQueryError`` for a query the engine refuses."""
    return RetrievalQuery(
        text=request.query,
        owner_id=owner_id,
        limit=request.limit,
        filters=RetrievalFilters(
            memory_types=frozenset(request.memory_types) if request.memory_types else None,
            observed_from=request.observed_from,
            observed_to=request.observed_to,
            include_superseded=request.include_superseded,
            include_expired=request.include_expired,
            include_sensitive=True,
        ),
    )


def to_memory_search_response(result: RetrievalResult) -> MemorySearchResponse:
    return MemorySearchResponse(
        query=result.query,
        items=[
            MemorySearchHit(
                memory=to_memory_response(item.memory),
                rank=item.rank,
                score=item.score,
                rerank_score=item.rerank_score,
                matched_by=[
                    MemorySearchMatch(leg=leg, rank=hit.rank, score=hit.score)
                    for leg, hit in sorted(item.legs.items(), key=lambda pair: pair[1].rank)
                ],
                matched_names=list(item.matched_names),
                sources=[
                    MemorySearchSource(
                        raw_message_id=source.raw_message_id,
                        role=source.role,
                        source=source.source,
                        sent_at=source.sent_at,
                        evidence=source.evidence,
                        content=source.content,
                    )
                    for source in item.sources
                ],
                entities=[
                    MemorySearchEntity(
                        entity_id=entity.entity_id, entity_type=entity.entity_type, name=entity.name
                    )
                    for entity in item.entities
                ],
            )
            for item in result.items
        ],
        legs=[
            MemorySearchLeg(
                leg=str(report.leg),
                used=report.used,
                candidates=report.candidates,
                duration_ms=report.duration_ms,
                error=report.error,
            )
            for report in result.legs
        ],
        embedding_space=result.embedding_space,
        reranked=result.reranked,
        degraded=result.degraded,
        duration_ms=result.duration_ms,
    )
