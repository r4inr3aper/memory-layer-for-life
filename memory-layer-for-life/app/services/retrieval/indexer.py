"""Keeps memory embeddings current: the index semantic retrieval searches.

Embeddings are derived data. The indexer finds memories whose embedding in the configured
space is missing or may be stale, builds each one's document, and embeds only those whose
document hash differs from what was stored, so nothing is paid for twice. Embedding calls
are made per owner and attributed to them in the call log.

It is safe to run anywhere, any number of times: a pass pages through memories by id,
every write is an upsert keyed on memory and space, and a memory deleted meanwhile is
skipped. If the provider fails, the pass stops (no point hammering it) and the next pass
continues where the index is still behind. The API runs ``IndexLoop``;
``scripts/index_memories.py`` runs a pass, a full check, or a rebuild by hand.
"""

import asyncio
import itertools
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.session import transaction
from app.domain.enums import LlmCallOrigin
from app.domain.errors import IntegrationError
from app.integrations.embeddings.base import Embedder, EmbeddingInputType
from app.integrations.llm_calls import LlmCallContext
from app.repositories.embedding_repository import EmbeddingRepository, IndexCandidate
from app.services.pacing import ALWAYS_ON, BackgroundPacer
from app.services.retrieval.documents import DOCUMENT_VERSION, document_sha256, memory_document

if TYPE_CHECKING:
    import uuid

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE: Final = 64


class IndexMode(StrEnum):
    # Memories with no embedding, or changed since embedded. What the loop runs.
    CHANGED = "changed"
    # Every memory, re-embedding only those whose document no longer matches.
    VERIFY = "verify"
    # Every memory, re-embedded regardless. For a suspected bad index.
    REBUILD = "rebuild"


@dataclass(frozen=True, slots=True)
class IndexReport:
    examined: int = 0
    embedded: int = 0
    unchanged: int = 0
    failed: int = 0
    tokens: int = 0
    # Set when the provider failed and the pass stopped early.
    stopped_by: str | None = None


@dataclass(frozen=True, slots=True)
class _Work:
    candidate: IndexCandidate
    document: str
    sha256: str


class MemoryIndexer:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        clock: Clock = utc_now,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._session_factory = session_factory
        self._embedder = embedder
        self._batch_size = batch_size
        self._clock = clock

    @property
    def space_key(self) -> str:
        return self._embedder.space.key

    async def run(
        self, mode: IndexMode = IndexMode.CHANGED, *, limit: int | None = None
    ) -> IndexReport:
        """One pass. ``limit`` caps how many memories are examined."""
        report = IndexReport()
        after: uuid.UUID | None = None
        while limit is None or report.examined < limit:
            batch_size = (
                self._batch_size
                if limit is None
                else min(self._batch_size, limit - report.examined)
            )
            async with self._session_factory() as session:
                candidates = await EmbeddingRepository(session).candidates(
                    self._embedder.space,
                    after=after,
                    limit=batch_size,
                    changed_only=mode is IndexMode.CHANGED,
                )
            if not candidates:
                break
            after = candidates[-1].memory_id
            report = await self._index_batch(candidates, mode, report)
            if report.stopped_by is not None:
                break
        if report.embedded or report.failed:
            logger.info(
                "memory_index_pass",
                mode=mode.value,
                space=self.space_key,
                examined=report.examined,
                embedded=report.embedded,
                unchanged=report.unchanged,
                failed=report.failed,
                tokens=report.tokens,
                stopped_by=report.stopped_by,
            )
        return report

    async def prune_other_spaces(self) -> int:
        """Delete embeddings of every space but the configured one."""
        async with transaction(self._session_factory) as session:
            return await EmbeddingRepository(session).delete_other_spaces(self._embedder.space)

    async def coverage(self) -> tuple[int, int]:
        async with self._session_factory() as session:
            return await EmbeddingRepository(session).coverage(self._embedder.space)

    async def _index_batch(
        self, candidates: list[IndexCandidate], mode: IndexMode, report: IndexReport
    ) -> IndexReport:
        current: list[uuid.UUID] = []
        work: list[_Work] = []
        for candidate in candidates:
            document = memory_document(
                candidate.memory_type, candidate.content, candidate.entity_names
            )
            sha256 = document_sha256(document)
            if (
                mode is not IndexMode.REBUILD
                and candidate.stored_sha256 == sha256
                and candidate.stored_document_version == DOCUMENT_VERSION
            ):
                current.append(candidate.memory_id)
            else:
                work.append(_Work(candidate, document, sha256))
        report = replace(
            report,
            examined=report.examined + len(candidates),
            unchanged=report.unchanged + len(current),
        )
        if current:
            async with transaction(self._session_factory) as session:
                await EmbeddingRepository(session).mark_current(
                    current, self._embedder.space, now=self._clock()
                )

        # One call per owner, so each call's cost is attributed to the person it is for.
        by_owner = itertools.groupby(
            sorted(work, key=lambda item: str(item.candidate.owner_id)),
            key=lambda item: item.candidate.owner_id,
        )
        for owner_id, owned in by_owner:
            items = list(owned)
            try:
                embeddings = await self._embedder.embed(
                    [item.document for item in items],
                    input_type=EmbeddingInputType.DOCUMENT,
                    context=LlmCallContext(origin=LlmCallOrigin.INDEXING, user_id=owner_id),
                )
            except IntegrationError as error:
                logger.warning("memory_index_provider_failed", error_code=error.code)
                return replace(report, failed=report.failed + len(items), stopped_by=error.message)
            if len(embeddings.vectors) != len(items):
                # The client checks this already; a mismatch here would misfile vectors.
                raise RuntimeError("The embedder returned a different number of vectors.")
            async with transaction(self._session_factory) as session:
                repository = EmbeddingRepository(session)
                now = self._clock()
                for item, vector in zip(items, embeddings.vectors, strict=True):
                    await repository.upsert(
                        memory_id=item.candidate.memory_id,
                        space=self._embedder.space,
                        vector=vector,
                        content_sha256=item.sha256,
                        document_version=DOCUMENT_VERSION,
                        now=now,
                    )
            report = replace(
                report,
                embedded=report.embedded + len(items),
                tokens=report.tokens + embeddings.total_tokens,
            )
        return report


class IndexLoop:
    """Runs an indexing pass every ``interval_seconds`` while the API runs, so a new
    memory becomes findable by meaning within that time, whatever created it. When the
    database should sleep, passes are spaced out while nobody uses the app
    (``app.services.pacing``); each pass embeds everything outstanding."""

    def __init__(
        self,
        indexer: MemoryIndexer,
        *,
        interval_seconds: float,
        pacer: BackgroundPacer = ALWAYS_ON,
    ) -> None:
        self._indexer = indexer
        self._interval_seconds = interval_seconds
        self._pacer = pacer
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="memory-index-loop")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self._indexer.run(IndexMode.CHANGED)
            except Exception:
                # A failed pass must not end the loop; the next pass tries again.
                logger.exception("memory_index_pass_failed")
            await self._pacer.sleep(self._interval_seconds)
