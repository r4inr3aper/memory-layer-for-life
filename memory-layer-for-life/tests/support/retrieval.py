"""Building small, exact memory stores for retrieval tests, through the real pipeline."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import transaction
from app.domain.enums import EntityType, LlmCallOrigin, MemoryType, MessageSource
from app.domain.retrieval import RetrievalFilters, RetrievalQuery
from app.integrations.embeddings.base import Embedder, Reranker
from app.integrations.llm_calls import LlmCallContext
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from app.repositories.user_repository import UserRepository
from app.schemas.extraction import ExtractionOutput
from app.schemas.raw_message import RawMessageCreate
from app.services.retrieval.engine import RetrievalConfig, RetrievalEngine, RetrievalResult
from tests.support.assistant import new_principal
from tests.support.extraction import ScriptedExtractor, evidence, extraction, memory, mention
from tests.support.pipeline import FakeClock, PipelineHarness

# The fake embedder's vectors are sparse; real models need a higher bar (0.3 by default).
TEST_MIN_SIMILARITY = 0.15


def fact(
    content: str,
    message: str,
    *names: str,
    memory_type: MemoryType = MemoryType.SEMANTIC_FACT,
) -> ExtractionOutput:
    """One memory resting on the whole message, linked to people named in it."""
    return extraction(
        memory(
            content,
            memory_type=memory_type,
            evidence_refs=[evidence(0, message)],
            mention_indexes=list(range(len(names))),
        ),
        mentions=[mention(name, entity_type=EntityType.PERSON) for name in names],
    )


async def app_user(
    session_factory: async_sessionmaker[AsyncSession], clock: FakeClock, name: str = "Ada"
) -> uuid.UUID:
    principal = new_principal(name)
    async with transaction(session_factory) as session:
        await UserRepository(session).upsert(
            principal.id, email=principal.email, display_name=principal.display_name, now=clock()
        )
    return principal.id


async def remember(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    message: str,
    output: ExtractionOutput,
    *,
    owner: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Capture one message for the owner, extract ``output`` from it, and return the ids of
    the memories that run made, in order."""
    extractor.use_script(output)
    [unit] = await harness.ingestion.ingest(
        [[RawMessageCreate(source=MessageSource.API_INPUT, content=message)]], owner_id=owner
    )
    await harness.runner.process_runs([unit.run.id])
    async with harness.session_factory() as session:
        rows = await session.scalars(
            select(Memory.id)
            .join(ExtractionResult, ExtractionResult.id == Memory.origin_extraction_result_id)
            .where(ExtractionResult.processing_run_id == unit.run.id)
            .order_by(Memory.origin_ordinal)
        )
        ids = list(rows)
    assert ids, f"no memory was made from {message!r}"
    return ids


async def change_memory(
    session_factory: async_sessionmaker[AsyncSession], memory_id: uuid.UUID, **values: Any
) -> None:
    async with transaction(session_factory) as session:
        await session.execute(update(Memory).where(Memory.id == memory_id).values(**values))


def engine(
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    *,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    **config: Any,
) -> RetrievalEngine:
    config.setdefault("min_semantic_similarity", TEST_MIN_SIMILARITY)
    return RetrievalEngine(
        session_factory,
        embedder=embedder,
        reranker=reranker,
        config=RetrievalConfig(**config),
        clock=clock,
    )


async def search(
    retrieval: RetrievalEngine,
    text: str,
    *,
    owner: uuid.UUID | None = None,
    limit: int = 10,
    **filters: Any,
) -> RetrievalResult:
    return await retrieval.search(
        RetrievalQuery(text=text, owner_id=owner, limit=limit, filters=RetrievalFilters(**filters)),
        context=LlmCallContext(origin=LlmCallOrigin.RETRIEVAL, user_id=owner),
    )


def contents(result: RetrievalResult) -> list[str]:
    return [item.memory.content for item in result.items]


def legs_of(result: RetrievalResult, content: str) -> set[str]:
    for item in result.items:
        if item.memory.content == content:
            return {str(leg) for leg in item.legs}
    raise AssertionError(f"{content!r} was not returned")


def report(result: RetrievalResult, leg: str) -> Any:
    return next(item for item in result.legs if str(item.leg) == leg)


__all__: Sequence[str] = (
    "TEST_MIN_SIMILARITY",
    "app_user",
    "change_memory",
    "contents",
    "engine",
    "fact",
    "legs_of",
    "remember",
    "report",
    "search",
)
