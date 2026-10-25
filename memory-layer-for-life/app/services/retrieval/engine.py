"""The retrieval engine: from a question to the memories that bear on it, with the
evidence each rests on.

A search runs in five steps:

1. The query is validated and normalized (``RetrievalQuery``).
2. Three legs rank candidates independently, each already restricted to the owner and the
   filters: words (full-text search), names (linked entities), and meaning (embeddings).
   Words and names run while the query is being embedded.
3. Their rankings are fused by reciprocal rank fusion.
4. Optionally, a reranker (a cross-encoder) reorders the best fused candidates by reading
   the query and each memory together.
5. The winners are loaded from the source of truth with their evidence and entities.

The same text is returned once: when several memories say exactly the same thing (the
same fact told twice), only the best ranked of them is a result.

Sensitive memories are only searched when the query asks for them (the owner's own
search), and even then never sent to the reranker: they keep their fused order after the
reranked results.

Without an embedding provider the search uses words and names, and the meaning leg is
reported as not used. When a configured provider fails, the search continues without it
and says why (``LegReport.error``, so ``RetrievalResult.degraded``); the same holds for the
reranker. A failing database is not hidden: it fails the search.
"""

import asyncio
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.domain.enums import EntityType, MessageSource, RetrievalLeg, Sensitivity, SourceRole
from app.domain.errors import IntegrationError
from app.domain.normalization import normalize_for_matching
from app.domain.retrieval import (
    DEFAULT_RRF_K,
    FusedCandidate,
    LegHit,
    RetrievalQuery,
    fuse,
    lexical_terms,
    ranked_hits,
)
from app.integrations.embeddings.base import Embedder, EmbeddingInputType, Reranker
from app.integrations.llm_calls import LlmCallContext
from app.models.memory import Memory
from app.repositories.retrieval_repository import RetrievalRepository
from app.services.queries import MemoryView
from app.services.retrieval.documents import memory_document

logger = structlog.get_logger(__name__)

_MAX_EVIDENCE_CHARS: Final = 500


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    # How many candidates each leg contributes to fusion.
    candidate_depth: int = 50
    rrf_k: int = DEFAULT_RRF_K
    weights: Mapping[RetrievalLeg, float] = field(
        default_factory=lambda: {
            RetrievalLeg.LEXICAL: 1.0,
            RetrievalLeg.SEMANTIC: 1.0,
            RetrievalLeg.ENTITY: 1.0,
        }
    )
    # Below this cosine similarity a memory is not considered related at all. Model
    # specific: measure it with the retrieval evaluation before changing it.
    min_semantic_similarity: float = 0.3
    # How close a misspelled name must be to count (pg_trgm strict word similarity).
    min_name_similarity: float = 0.5
    # How many fused candidates the reranker reads.
    rerank_depth: int = 30

    def __post_init__(self) -> None:
        if self.candidate_depth < 1 or self.rerank_depth < 1 or self.rrf_k < 1:
            raise ValueError("depths and k must be positive")
        if not -1.0 <= self.min_semantic_similarity <= 1.0:
            raise ValueError("min_semantic_similarity is a cosine similarity")
        if not 0.0 < self.min_name_similarity <= 1.0:
            raise ValueError("min_name_similarity is between 0 and 1")


@dataclass(frozen=True, slots=True)
class RetrievedSource:
    """A message the memory rests on."""

    raw_message_id: uuid.UUID
    role: SourceRole
    source: MessageSource
    sent_at: datetime | None
    evidence: str | None
    content: str


@dataclass(frozen=True, slots=True)
class RetrievedEntity:
    entity_id: uuid.UUID
    entity_type: EntityType
    name: str


@dataclass(frozen=True, slots=True)
class RetrievedMemory:
    memory: MemoryView
    rank: int
    # Reciprocal-rank-fusion score; comparable only within one search.
    score: float
    legs: Mapping[RetrievalLeg, LegHit]
    rerank_score: float | None
    # Names of the query that linked this memory, from the entity leg.
    matched_names: tuple[str, ...]
    sources: tuple[RetrievedSource, ...]
    entities: tuple[RetrievedEntity, ...]


@dataclass(frozen=True, slots=True)
class LegReport:
    leg: RetrievalLeg | str
    used: bool
    candidates: int
    duration_ms: int
    # Why a configured leg failed; the search continued without it. None when the leg ran,
    # or was not configured (then ``used`` is false).
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    query: str
    items: tuple[RetrievedMemory, ...]
    legs: tuple[LegReport, ...]
    embedding_space: str | None
    reranked: bool
    duration_ms: int

    @property
    def degraded(self) -> bool:
        return any(leg.error is not None for leg in self.legs)


@dataclass(frozen=True, slots=True)
class _LegOutcome:
    hits: list[LegHit]
    report: LegReport
    names: dict[uuid.UUID, tuple[str, ...]] = field(default_factory=dict)


class RetrievalEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        embedder: Embedder | None,
        reranker: Reranker | None = None,
        config: RetrievalConfig | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        self._reranker = reranker
        self._config = config or RetrievalConfig()
        self._clock = clock

    @property
    def semantic_available(self) -> bool:
        return self._embedder is not None

    async def search(self, query: RetrievalQuery, *, context: LlmCallContext) -> RetrievalResult:
        started = time.monotonic()
        now = self._clock()
        depth = self._config.candidate_depth

        lexical, entity, query_vector = await asyncio.gather(
            self._lexical(query, depth, now),
            self._entity(query, depth, now),
            self._embed_query(query, context),
        )
        semantic = await self._semantic(query, query_vector, depth, now)

        outcomes = {
            RetrievalLeg.LEXICAL: lexical,
            RetrievalLeg.ENTITY: entity,
            RetrievalLeg.SEMANTIC: semantic,
        }
        fused = fuse(
            {leg: outcome.hits for leg, outcome in outcomes.items()},
            weights=self._config.weights,
            k=self._config.rrf_k,
        )
        reports = [outcome.report for outcome in outcomes.values()]

        rerank_scores: dict[uuid.UUID, float] = {}
        reranked = False
        loaded: dict[uuid.UUID, Memory] = {}
        if self._reranker is not None and len(fused) > 1:
            head = fused[: self._config.rerank_depth]
            loaded = await self._load(query.owner_id, [candidate.memory_id for candidate in head])
            rerank_report, rerank_scores = await self._rerank(query, head, loaded, context)
            reports.append(rerank_report)
            if rerank_scores:
                reranked = True
                fused = _apply_rerank(fused, rerank_scores)

        # Twice the page, so dropping repeated text still fills it.
        pool = fused[: query.limit * 2]
        missing = [candidate.memory_id for candidate in pool if candidate.memory_id not in loaded]
        if missing:
            loaded.update(await self._load(query.owner_id, missing))

        names = entity.names
        items: list[RetrievedMemory] = []
        seen_texts: set[str] = set()
        for candidate in pool:
            if len(items) == query.limit:
                break
            memory = loaded.get(candidate.memory_id)
            if memory is None:  # deleted since it was ranked
                continue
            text = memory.normalized_content or normalize_for_matching(memory.content)
            if text in seen_texts:
                continue
            seen_texts.add(text)
            items.append(
                _retrieved(
                    memory,
                    rank=len(items) + 1,
                    candidate=candidate,
                    rerank_score=rerank_scores.get(candidate.memory_id),
                    matched_names=names.get(candidate.memory_id, ()),
                )
            )

        result = RetrievalResult(
            query=query.text,
            items=tuple(items),
            legs=tuple(reports),
            embedding_space=self._embedder.space.key if self._embedder is not None else None,
            reranked=reranked,
            duration_ms=_elapsed_ms(started),
        )
        logger.info(
            "memory_search",
            results=len(items),
            degraded=result.degraded,
            reranked=reranked,
            duration_ms=result.duration_ms,
            legs={str(report.leg): report.candidates for report in reports},
        )
        return result

    # --- Legs ------------------------------------------------------------------------

    async def _lexical(self, query: RetrievalQuery, depth: int, now: datetime) -> _LegOutcome:
        started = time.monotonic()
        terms = lexical_terms(query.text)
        async with self._session_factory() as session:
            scored = await RetrievalRepository(session).lexical(query, terms, limit=depth, now=now)
        hits = ranked_hits(scored)
        return _LegOutcome(
            hits=hits,
            report=LegReport(
                leg=RetrievalLeg.LEXICAL,
                used=bool(terms),
                candidates=len(hits),
                duration_ms=_elapsed_ms(started),
            ),
        )

    async def _entity(self, query: RetrievalQuery, depth: int, now: datetime) -> _LegOutcome:
        started = time.monotonic()
        async with self._session_factory() as session:
            found = await RetrievalRepository(session).entity(
                query,
                query_text=normalize_for_matching(query.text),
                min_name_similarity=self._config.min_name_similarity,
                limit=depth,
                now=now,
            )
        hits = ranked_hits([(hit.memory_id, hit.score) for hit in found])
        return _LegOutcome(
            hits=hits,
            report=LegReport(
                leg=RetrievalLeg.ENTITY,
                used=True,
                candidates=len(hits),
                duration_ms=_elapsed_ms(started),
            ),
            names={hit.memory_id: hit.names for hit in found},
        )

    async def _embed_query(
        self, query: RetrievalQuery, context: LlmCallContext
    ) -> tuple[tuple[float, ...] | None, LegReport | None]:
        if self._embedder is None:
            return None, None
        started = time.monotonic()
        try:
            embeddings = await self._embedder.embed(
                [query.text], input_type=EmbeddingInputType.QUERY, context=context
            )
        except IntegrationError as error:
            logger.warning("memory_search_embedding_failed", error_code=error.code)
            return None, LegReport(
                leg=RetrievalLeg.SEMANTIC,
                used=False,
                candidates=0,
                duration_ms=_elapsed_ms(started),
                error=error.message,
            )
        return embeddings.vectors[0], None

    async def _semantic(
        self,
        query: RetrievalQuery,
        embedded: tuple[tuple[float, ...] | None, LegReport | None],
        depth: int,
        now: datetime,
    ) -> _LegOutcome:
        vector, failure = embedded
        if failure is not None:
            return _LegOutcome(hits=[], report=failure)
        if vector is None or self._embedder is None:
            # Not configured is not a failure: the search is complete for what is set up.
            return _LegOutcome(
                hits=[],
                report=LegReport(
                    leg=RetrievalLeg.SEMANTIC, used=False, candidates=0, duration_ms=0
                ),
            )
        started = time.monotonic()
        async with self._session_factory() as session:
            scored = await RetrievalRepository(session).semantic(
                query,
                space=self._embedder.space,
                vector=vector,
                min_similarity=self._config.min_semantic_similarity,
                limit=depth,
                now=now,
            )
        hits = ranked_hits(scored)
        return _LegOutcome(
            hits=hits,
            report=LegReport(
                leg=RetrievalLeg.SEMANTIC,
                used=True,
                candidates=len(hits),
                duration_ms=_elapsed_ms(started),
            ),
        )

    # --- Reranking and loading -------------------------------------------------------

    async def _rerank(
        self,
        query: RetrievalQuery,
        head: Sequence[FusedCandidate],
        loaded: Mapping[uuid.UUID, Memory],
        context: LlmCallContext,
    ) -> tuple[LegReport, dict[uuid.UUID, float]]:
        assert self._reranker is not None
        started = time.monotonic()
        present = [
            candidate
            for candidate in head
            if candidate.memory_id in loaded and not _sensitive(loaded[candidate.memory_id])
        ]
        if not present:
            return LegReport(leg="rerank", used=False, candidates=0, duration_ms=0), {}
        documents = [_document(loaded[candidate.memory_id]) for candidate in present]
        try:
            scores = await self._reranker.rerank(query.text, documents, context=context)
        except IntegrationError as error:
            logger.warning("memory_search_rerank_failed", error_code=error.code)
            return (
                LegReport(
                    leg="rerank",
                    used=False,
                    candidates=0,
                    duration_ms=_elapsed_ms(started),
                    error=error.message,
                ),
                {},
            )
        by_memory = {present[score.index].memory_id: score.score for score in scores}
        return (
            LegReport(
                leg="rerank",
                used=True,
                candidates=len(by_memory),
                duration_ms=_elapsed_ms(started),
            ),
            by_memory,
        )

    async def _load(
        self, owner_id: uuid.UUID | None, memory_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, Memory]:
        async with self._session_factory() as session:
            return await RetrievalRepository(session).load(owner_id, memory_ids)


def _apply_rerank(
    fused: Sequence[FusedCandidate], scores: Mapping[uuid.UUID, float]
) -> list[FusedCandidate]:
    """Reranked candidates first, by the reranker's score; the rest keep their fused
    order after them. Ties keep the fused order."""
    position = {candidate.memory_id: index for index, candidate in enumerate(fused)}
    reranked = sorted(
        (candidate for candidate in fused if candidate.memory_id in scores),
        key=lambda candidate: (-scores[candidate.memory_id], position[candidate.memory_id]),
    )
    rest = [candidate for candidate in fused if candidate.memory_id not in scores]
    return reranked + rest


def _sensitive(memory: Memory) -> bool:
    return memory.metadata_.get("sensitivity") == Sensitivity.SENSITIVE.value


def _document(memory: Memory) -> str:
    return memory_document(
        memory.memory_type,
        memory.content,
        (link.entity.canonical_name for link in memory.memory_entities),
    )


def _retrieved(
    memory: Memory,
    *,
    rank: int,
    candidate: FusedCandidate,
    rerank_score: float | None,
    matched_names: tuple[str, ...],
) -> RetrievedMemory:
    sources = sorted(
        memory.sources,
        key=lambda source: (
            source.source_role != SourceRole.SUPPORTING.value,
            source.raw_message.source_created_at is None,
            source.raw_message.source_created_at,
            str(source.raw_message_id),
        ),
    )
    return RetrievedMemory(
        memory=MemoryView.of(memory),
        rank=rank,
        score=candidate.score,
        legs=dict(candidate.hits),
        rerank_score=rerank_score,
        matched_names=matched_names,
        sources=tuple(
            RetrievedSource(
                raw_message_id=source.raw_message_id,
                role=SourceRole(source.source_role),
                source=MessageSource(source.raw_message.source),
                sent_at=source.raw_message.source_created_at,
                evidence=source.evidence_text,
                content=source.raw_message.content[:_MAX_EVIDENCE_CHARS],
            )
            for source in sources
        ),
        entities=tuple(
            RetrievedEntity(
                entity_id=link.entity_id,
                entity_type=EntityType(link.entity.entity_type),
                name=link.entity.canonical_name,
            )
            for link in sorted(memory.memory_entities, key=lambda link: link.entity.canonical_name)
        ),
    )


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))
