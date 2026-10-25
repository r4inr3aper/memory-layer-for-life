"""The retrieval engine against PostgreSQL with pgvector and pg_trgm: each leg, fusion,
filters, owners, degradation, staleness, reranking, and evidence.

Memories are made by the real pipeline around a scripted extractor, and embedded by a
deterministic embedder, so every result here is exact and repeatable.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import MemoryStatus, MemoryType, RetrievalLeg
from app.domain.errors import IntegrationError
from app.services.retrieval.indexer import MemoryIndexer
from tests.integration.conftest import HarnessFactory
from tests.support.embeddings import FakeEmbedder, FakeReranker
from tests.support.extraction import ScriptedExtractor
from tests.support.pipeline import FakeClock, PipelineHarness
from tests.support.retrieval import (
    app_user,
    change_memory,
    contents,
    engine,
    fact,
    legs_of,
    remember,
    report,
    search,
)

RAJU = "Raju owes the user 2980 rupees."
SISTER = "The user's sister Priya lives in Pune."
ALMONDS = "Buy almonds."


@pytest.fixture
def extractor() -> ScriptedExtractor:
    return ScriptedExtractor()


@pytest.fixture
def harness(make_harness: HarnessFactory, extractor: ScriptedExtractor) -> PipelineHarness:
    return make_harness(extractor)


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder(concepts=[("sister", "sibling"), ("petrol", "fuel")])


async def index(
    session_factory: async_sessionmaker[AsyncSession], clock: FakeClock, embedder: FakeEmbedder
) -> None:
    report = await MemoryIndexer(session_factory, embedder, clock=clock).run()
    assert report.stopped_by is None


# --- Words -----------------------------------------------------------------------------


async def test_a_plain_question_finds_the_memory_by_its_words(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    await remember(harness, extractor, "Raju owes me 2980", fact(RAJU, "Raju owes me 2980"))
    await remember(harness, extractor, "buy almonds", fact(ALMONDS, "buy almonds"))

    result = await search(engine(session_factory, clock), "How much does Raju owe me?")

    assert contents(result) == [RAJU]
    assert legs_of(result, RAJU) == {"lexical"}
    # Without an embedding provider the meaning leg is simply not used: not a failure.
    semantic = report(result, "semantic")
    assert (semantic.used, semantic.error, result.degraded) == (False, None, False)
    assert result.embedding_space is None


async def test_other_forms_of_a_word_are_found(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    content = "Check the credit-card bills."
    await remember(
        harness, extractor, "check credit card bills", fact(content, "check credit card bills")
    )

    result = await search(engine(session_factory, clock), "bill")

    assert contents(result) == [content]


async def test_a_question_made_only_of_question_words_searches_no_words(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    await remember(harness, extractor, "Raju owes me 2980", fact(RAJU, "Raju owes me 2980"))

    result = await search(engine(session_factory, clock), "what do you remember about me?")

    assert contents(result) == []
    assert report(result, "lexical").used is False


async def test_amounts_and_rare_words_are_searchable(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    await remember(harness, extractor, "Raju owes me 2980", fact(RAJU, "Raju owes me 2980"))
    content = "Research Context7 and build something similar."
    await remember(harness, extractor, "research context7", fact(content, "research context7"))

    retrieval = engine(session_factory, clock)

    assert contents(await search(retrieval, "2980")) == [RAJU]
    assert contents(await search(retrieval, "context7")) == [content]


# --- Names -----------------------------------------------------------------------------


async def test_a_name_finds_memories_linked_to_that_person_even_when_their_text_lacks_it(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    message = "Priya moved to Pune last year"
    content = "She moved to Pune last year."
    await remember(harness, extractor, message, fact(content, message, "Priya"))

    result = await search(engine(session_factory, clock), "Priya")

    assert contents(result) == [content]
    assert legs_of(result, content) == {"entity"}
    assert result.items[0].matched_names == ("Priya",)


async def test_a_misspelled_name_still_finds_the_person(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    message = "Priya moved to Pune last year"
    content = "She moved to Pune last year."
    await remember(harness, extractor, message, fact(content, message, "Priya"))

    result = await search(engine(session_factory, clock), "what about priyaa?")

    assert contents(result) == [content]
    hit = result.items[0].legs[RetrievalLeg.ENTITY]
    assert 0.5 <= hit.score < 1.0  # close, not exact


async def test_a_short_name_must_be_exact_and_tom_is_not_found_in_tomorrow(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    content = "Paid back 110."
    await remember(harness, extractor, "Tom paid 110", fact(content, "Tom paid 110", "Tom"))
    retrieval = engine(session_factory, clock)

    assert contents(await search(retrieval, "plans for tomorrow")) == []
    assert contents(await search(retrieval, "Tom")) == [content]
    assert contents(await search(retrieval, "tom?")) == [content]


# --- Meaning ---------------------------------------------------------------------------


async def test_meaning_finds_a_paraphrase_the_words_and_names_miss(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    embedder: FakeEmbedder,
) -> None:
    message = "My sister Priya lives in Pune"
    await remember(harness, extractor, message, fact(SISTER, message, "Priya"))
    await remember(harness, extractor, "buy almonds", fact(ALMONDS, "buy almonds"))
    await index(session_factory, clock, embedder)

    result = await search(engine(session_factory, clock, embedder=embedder), "sibling")

    # Found by meaning only; the unrelated memory is below the similarity bar.
    assert contents(result) == [SISTER]
    assert legs_of(result, SISTER) == {"semantic"}
    assert result.embedding_space == "fake/bag-of-words/256"
    assert embedder.calls[-1].input_type.value == "query"


async def test_memories_several_legs_agree_on_rank_first(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    embedder: FakeEmbedder,
) -> None:
    message = "My sister Priya lives in Pune"
    await remember(harness, extractor, message, fact(SISTER, message, "Priya"))
    weather = "Pune is hot in May."
    await remember(harness, extractor, "pune is hot in may", fact(weather, "pune is hot in may"))
    await index(session_factory, clock, embedder)

    result = await search(engine(session_factory, clock, embedder=embedder), "Priya Pune")

    assert contents(result)[0] == SISTER
    assert legs_of(result, SISTER) == {"lexical", "entity", "semantic"}
    assert result.items[0].score > result.items[1].score


async def test_a_failing_embedding_provider_degrades_to_words_and_names(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    await remember(harness, extractor, "Raju owes me 2980", fact(RAJU, "Raju owes me 2980"))
    failing = FakeEmbedder(fail_with=IntegrationError("Voyage AI", "could not be reached."))

    result = await search(engine(session_factory, clock, embedder=failing), "Raju")

    assert contents(result) == [RAJU]
    assert result.degraded is True
    assert report(result, "semantic").error == "Voyage AI: could not be reached."


async def test_an_embedding_older_than_its_memory_is_not_trusted_until_refreshed(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    embedder: FakeEmbedder,
) -> None:
    message = "My sister Priya lives in Pune"
    [memory_id] = await remember(harness, extractor, message, fact(SISTER, message))
    await index(session_factory, clock, embedder)
    clock.advance(minutes=1)
    corrected = "The user's sister Priya lives in Mumbai."
    await change_memory(session_factory, memory_id, content=corrected, updated_at=clock())
    retrieval = engine(session_factory, clock, embedder=embedder)

    stale = await search(retrieval, "sibling")
    await index(session_factory, clock, embedder)
    fresh = await search(retrieval, "sibling")

    assert contents(stale) == []
    assert contents(fresh) == [corrected]


# --- Owners and filters ----------------------------------------------------------------


async def test_another_owner_s_memories_are_never_found_by_any_leg(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    embedder: FakeEmbedder,
) -> None:
    mine = await app_user(session_factory, clock, "Mine")
    theirs = await app_user(session_factory, clock, "Theirs")
    message = "My sister Priya lives in Pune"
    their_fact = "Their sister Priya lives in Delhi."
    await remember(harness, extractor, message, fact(SISTER, message, "Priya"), owner=mine)
    their_message = "my sister priya lives in delhi"
    await remember(
        harness, extractor, their_message, fact(their_fact, their_message, "priya"), owner=theirs
    )
    operator_fact = "Priya from work called."
    operator_message = "priya from work called"
    await remember(
        harness, extractor, operator_message, fact(operator_fact, operator_message, "priya")
    )
    await index(session_factory, clock, embedder)
    retrieval = engine(session_factory, clock, embedder=embedder)

    # Each question would match across stores by words, names, or meaning; no leg may cross.
    for question in ("Priya", "sibling", "sister Priya Pune Delhi work"):
        assert contents(await search(retrieval, question, owner=mine)) == [SISTER]
        assert contents(await search(retrieval, question, owner=theirs)) == [their_fact]
        assert set(contents(await search(retrieval, question))) <= {operator_fact}
    assert contents(await search(retrieval, "Priya")) == [operator_fact]


async def test_retracted_and_superseded_memories_are_left_out_unless_asked_for(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    [retracted] = await remember(
        harness, extractor, "Raju owes me 2980", fact(RAJU, "Raju owes me 2980")
    )
    old = "Raju lives in Delhi."
    new = "Raju lives in Pune now."
    [old_id] = await remember(
        harness, extractor, "raju lives in delhi", fact(old, "raju lives in delhi")
    )
    [new_id] = await remember(
        harness, extractor, "raju lives in pune now", fact(new, "raju lives in pune now")
    )
    await change_memory(session_factory, retracted, status=MemoryStatus.RETRACTED.value)
    await change_memory(session_factory, new_id, supersedes_memory_id=old_id)
    retrieval = engine(session_factory, clock)

    default = await search(retrieval, "Raju")
    everything = await search(
        retrieval,
        "Raju",
        statuses=frozenset(MemoryStatus),
        include_superseded=True,
    )

    assert contents(default) == [new]
    assert set(contents(everything)) == {RAJU, old, new}


async def test_expired_memories_are_left_out_unless_asked_for(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    [memory_id] = await remember(
        harness, extractor, "Raju owes me 2980", fact(RAJU, "Raju owes me 2980")
    )
    await change_memory(session_factory, memory_id, valid_until=clock() - timedelta(days=1))
    retrieval = engine(session_factory, clock)

    assert contents(await search(retrieval, "Raju")) == []
    assert contents(await search(retrieval, "Raju", include_expired=True)) == [RAJU]


async def test_kinds_and_time_bounds_restrict_every_leg_before_ranking(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    task = "Pay Raju back."
    [fact_id] = await remember(
        harness, extractor, "Raju owes me 2980", fact(RAJU, "Raju owes me 2980")
    )
    [task_id] = await remember(
        harness,
        extractor,
        "pay raju back",
        fact(task, "pay raju back", memory_type=MemoryType.TASK),
    )
    await change_memory(session_factory, fact_id, observed_at=datetime(2026, 3, 1, tzinfo=UTC))
    await change_memory(session_factory, task_id, observed_at=datetime(2026, 9, 1, tzinfo=UTC))
    retrieval = engine(session_factory, clock)

    tasks = await search(retrieval, "Raju", memory_types=frozenset({MemoryType.TASK}))
    spring = await search(
        retrieval,
        "Raju",
        observed_from=datetime(2026, 1, 1, tzinfo=UTC),
        observed_to=datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert contents(tasks) == [task]
    assert contents(spring) == [RAJU]


# --- Reranking, evidence, limits -------------------------------------------------------


async def test_the_reranker_reorders_the_best_candidates(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    second = "Raju paid the deposit."
    await remember(
        harness, extractor, "Raju owes me 2980 rupees", fact(RAJU, "Raju owes me 2980 rupees")
    )
    await remember(
        harness, extractor, "raju paid the deposit", fact(second, "raju paid the deposit")
    )
    reranker = FakeReranker(prefer="deposit")
    retrieval = engine(session_factory, clock, reranker=reranker)

    result = await search(retrieval, "Raju 2980 rupees deposit")

    assert contents(result)[0] == second
    assert result.reranked is True
    assert result.items[0].rerank_score == 1.0
    [(query, documents)] = reranker.calls
    assert query == "Raju 2980 rupees deposit"
    assert any(document.startswith("Fact: ") for document in documents)


async def test_a_failing_reranker_keeps_the_fused_order(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    second = "Raju paid the deposit."
    await remember(
        harness, extractor, "Raju owes me 2980 rupees", fact(RAJU, "Raju owes me 2980 rupees")
    )
    await remember(
        harness, extractor, "raju paid the deposit", fact(second, "raju paid the deposit")
    )
    plain = await search(engine(session_factory, clock), "Raju 2980 rupees")
    failing = FakeReranker(fail_with=IntegrationError("Voyage AI", "failed (HTTP 500)."))

    result = await search(engine(session_factory, clock, reranker=failing), "Raju 2980 rupees")

    assert contents(result) == contents(plain)
    assert (result.reranked, result.degraded) == (False, True)


async def test_results_carry_the_messages_and_people_they_rest_on(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    message = "My sister Priya lives in Pune"
    await remember(harness, extractor, message, fact(SISTER, message, "Priya"))

    [item] = (await search(engine(session_factory, clock), "Priya")).items

    [source] = item.sources
    assert (source.evidence, source.content, source.role.value) == (message, message, "supporting")
    assert [(entity.name, entity.entity_type.value) for entity in item.entities] == [
        ("Priya", "person")
    ]
    assert item.memory.status is MemoryStatus.PROPOSED


async def test_the_limit_is_respected_and_ranks_are_consecutive(
    harness: PipelineHarness,
    extractor: ScriptedExtractor,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    for number in range(5):
        content = f"Raju note number {number}."
        await remember(
            harness, extractor, f"raju note {number}", fact(content, f"raju note {number}")
        )

    result = await search(engine(session_factory, clock), "Raju note", limit=3)

    assert [item.rank for item in result.items] == [1, 2, 3]
