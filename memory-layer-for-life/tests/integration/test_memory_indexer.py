"""The memory indexer against PostgreSQL with pgvector: what it embeds, what it leaves
alone, how it recovers, and how embeddings follow their memories."""

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import transaction
from app.domain.enums import LlmCallOrigin
from app.domain.errors import IntegrationError
from app.integrations.embeddings.base import EmbeddingInputType, EmbeddingSpace
from app.models.entity import Entity
from app.models.memory_embedding import MemoryEmbedding
from app.repositories.embedding_repository import EmbeddingRepository
from app.repositories.owned_memory_repository import OwnedMemoryRepository
from app.services.retrieval.documents import DOCUMENT_VERSION
from app.services.retrieval.indexer import IndexMode, MemoryIndexer
from tests.integration.conftest import HarnessFactory
from tests.support.embeddings import FakeEmbedder
from tests.support.extraction import ScriptedExtractor
from tests.support.pipeline import FakeClock, PipelineHarness
from tests.support.retrieval import app_user, change_memory, fact, remember


@pytest.fixture
def extractor() -> ScriptedExtractor:
    return ScriptedExtractor()


@pytest.fixture
def harness(make_harness: HarnessFactory, extractor: ScriptedExtractor) -> PipelineHarness:
    return make_harness(extractor)


def indexer(
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    embedder: FakeEmbedder,
    *,
    batch_size: int = 64,
) -> MemoryIndexer:
    return MemoryIndexer(session_factory, embedder, batch_size=batch_size, clock=clock)


async def embedding_count(
    session_factory: async_sessionmaker[AsyncSession], space: str | None = None
) -> int:
    async with session_factory() as session:
        statement = select(func.count()).select_from(MemoryEmbedding)
        if space is not None:
            statement = statement.where(MemoryEmbedding.embedding_space == space)
        return int(await session.scalar(statement) or 0)


async def test_new_memories_are_embedded_once(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    for number in range(3):
        await remember(
            harness, extractor, f"note {number}", fact(f"Note {number}.", f"note {number}")
        )
    embedder = FakeEmbedder()

    first = await indexer(session_factory, clock, embedder).run()
    again = await indexer(session_factory, clock, embedder).run()

    assert (first.examined, first.embedded, first.unchanged) == (3, 3, 0)
    assert (again.examined, again.embedded) == (0, 0)
    assert len(embedder.texts_embedded) == 3
    assert await embedding_count(session_factory, embedder.space.key) == 3
    assert await indexer(session_factory, clock, embedder).coverage() == (3, 3)


async def test_each_owner_s_memories_are_embedded_in_a_call_made_for_them(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    ada = await app_user(session_factory, clock, "Ada")
    bob = await app_user(session_factory, clock, "Bob")
    await remember(harness, extractor, "ada note", fact("Ada's note.", "ada note"), owner=ada)
    await remember(harness, extractor, "bob note", fact("Bob's note.", "bob note"), owner=bob)
    await remember(harness, extractor, "my note", fact("Operator note.", "my note"))
    embedder = FakeEmbedder()

    await indexer(session_factory, clock, embedder).run()

    assert {call.context.user_id for call in embedder.calls} == {ada, bob, None}
    assert all(len(call.texts) == 1 for call in embedder.calls)
    assert {call.context.origin for call in embedder.calls} == {LlmCallOrigin.INDEXING}
    assert {call.input_type for call in embedder.calls} == {EmbeddingInputType.DOCUMENT}


async def test_the_embedded_document_names_the_linked_people(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    message = "Priya moved to Pune last year"
    await remember(
        harness, extractor, message, fact("She moved to Pune last year.", message, "Priya")
    )
    embedder = FakeEmbedder()

    await indexer(session_factory, clock, embedder).run()

    assert embedder.texts_embedded == ["Fact: She moved to Pune last year.\nAbout: Priya"]


async def test_a_changed_memory_is_embedded_again(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    [memory_id] = await remember(harness, extractor, "note", fact("Old text.", "note"))
    embedder = FakeEmbedder()
    await indexer(session_factory, clock, embedder).run()
    clock.advance(minutes=1)
    await change_memory(session_factory, memory_id, content="New text.", updated_at=clock())

    report = await indexer(session_factory, clock, embedder).run()

    assert (report.examined, report.embedded) == (1, 1)
    assert embedder.texts_embedded[-1] == "Fact: New text."
    assert await embedding_count(session_factory) == 1


async def test_a_memory_touched_without_changing_its_document_is_not_paid_for_again(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    [memory_id] = await remember(harness, extractor, "note", fact("Same text.", "note"))
    embedder = FakeEmbedder()
    await indexer(session_factory, clock, embedder).run()
    clock.advance(minutes=1)
    await change_memory(session_factory, memory_id, updated_at=clock())

    touched = await indexer(session_factory, clock, embedder).run()
    after = await indexer(session_factory, clock, embedder).run()

    assert (touched.examined, touched.embedded, touched.unchanged) == (1, 0, 1)
    assert after.examined == 0
    assert len(embedder.texts_embedded) == 1


async def test_verify_finds_documents_changed_through_their_entities(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    message = "Priya moved to Pune last year"
    await remember(
        harness, extractor, message, fact("She moved to Pune last year.", message, "Priya")
    )
    embedder = FakeEmbedder()
    await indexer(session_factory, clock, embedder).run()
    async with transaction(session_factory) as session:
        await session.execute(update(Entity).values(canonical_name="Priya Sharma"))

    changed = await indexer(session_factory, clock, embedder).run(IndexMode.CHANGED)
    verified = await indexer(session_factory, clock, embedder).run(IndexMode.VERIFY)

    assert changed.examined == 0  # the memory row itself did not change
    assert (verified.examined, verified.embedded) == (1, 1)
    assert embedder.texts_embedded[-1].endswith("About: Priya Sharma")


async def test_rebuild_embeds_everything_again(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    for number in range(3):
        await remember(
            harness, extractor, f"note {number}", fact(f"Note {number}.", f"note {number}")
        )
    embedder = FakeEmbedder()
    await indexer(session_factory, clock, embedder).run()

    rebuilt = await indexer(session_factory, clock, embedder, batch_size=2).run(IndexMode.REBUILD)

    assert (rebuilt.examined, rebuilt.embedded) == (3, 3)
    assert len(embedder.texts_embedded) == 6


async def test_a_provider_failure_stops_the_pass_and_the_next_pass_catches_up(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    for number in range(3):
        await remember(
            harness, extractor, f"note {number}", fact(f"Note {number}.", f"note {number}")
        )
    embedder = FakeEmbedder(
        fail_with=IntegrationError("Voyage AI", "is limiting requests; try again shortly.")
    )

    failed = await indexer(session_factory, clock, embedder, batch_size=2).run()
    embedder.fail_with = None
    recovered = await indexer(session_factory, clock, embedder).run()

    assert failed.stopped_by == "Voyage AI: is limiting requests; try again shortly."
    assert (failed.embedded, failed.failed) == (0, 2)
    assert len(embedder.calls) == 2  # the failed call, then one successful pass
    assert recovered.embedded == 3


async def test_a_new_space_starts_empty_and_old_spaces_can_be_pruned(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    await remember(harness, extractor, "note", fact("A note.", "note"))
    old = FakeEmbedder(model="old-model")
    new = FakeEmbedder(model="new-model", dimensions=128)
    await indexer(session_factory, clock, old).run()

    before = await indexer(session_factory, clock, new).coverage()
    await indexer(session_factory, clock, new).run()
    pruned = await indexer(session_factory, clock, new).prune_other_spaces()

    assert before == (0, 1)
    assert pruned == 1
    assert await embedding_count(session_factory, old.space.key) == 0
    assert await embedding_count(session_factory, new.space.key) == 1


async def test_the_limit_caps_how_many_memories_a_pass_examines(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    for number in range(5):
        await remember(
            harness, extractor, f"note {number}", fact(f"Note {number}.", f"note {number}")
        )

    report = await indexer(session_factory, clock, FakeEmbedder(), batch_size=2).run(limit=3)

    assert (report.examined, report.embedded) == (3, 3)


async def test_an_embedding_goes_with_its_memory(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    owner = await app_user(session_factory, clock)
    await remember(harness, extractor, "note", fact("A note.", "note"), owner=owner)
    await indexer(session_factory, clock, FakeEmbedder()).run()

    async with transaction(session_factory) as session:
        await OwnedMemoryRepository(session).delete_for(owner)

    assert await embedding_count(session_factory) == 0


async def test_a_vector_must_have_its_space_s_dimensions(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    [memory_id] = await remember(harness, extractor, "note", fact("A note.", "note"))
    space = EmbeddingSpace(provider="fake", model="m", dimensions=3)

    with pytest.raises(IntegrityError):
        async with transaction(session_factory) as session:
            await EmbeddingRepository(session).upsert(
                memory_id=memory_id,
                space=space,
                vector=[0.1, 0.2],
                content_sha256="0" * 64,
                document_version=DOCUMENT_VERSION,
                now=clock(),
            )
