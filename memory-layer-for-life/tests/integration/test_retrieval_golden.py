"""Retrieval on the golden dataset: memories made from the author's real messages, asked
the questions of ``retrieval_queries.jsonl``.

No model is called. The fixture extractor makes exactly the dataset's expected memories,
and meaning comes from a deterministic fake. These tests hold the floor that words and
names must always reach, and that adding meaning never takes away from it. How well
meaning itself does is measured with the real model by ``scripts/run_retrieval_eval.py``,
never here.

Why the floor is exact: every keyword and name question shares a word or the name with
each of its answers, and at most eleven of the store's memories share any word with it.
Both negative questions share no word with any memory.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integrations.embeddings.base import EmbeddingInputType
from app.models.memory import Memory, is_sensitive
from app.services.retrieval.indexer import MemoryIndexer
from evaluation.fixture_extractor import GoldenFixtureExtractor
from evaluation.retrieval.dataset import (
    QueryCategory,
    check_against_golden,
    load_retrieval_cases,
)
from evaluation.retrieval.harness import (
    QueryResult,
    RetrievalEvaluation,
    build_golden_store,
    evaluate,
    memories_by_content,
    render_markdown,
)
from tests.integration.conftest import HarnessFactory
from tests.support.embeddings import FakeEmbedder
from tests.support.golden import require_golden_cases
from tests.support.pipeline import FakeClock
from tests.support.retrieval import engine

TIMEZONE_NAME = "Asia/Kolkata"
# Questions whose answers share words or a name with the question itself.
EXACT = frozenset({QueryCategory.KEYWORD, QueryCategory.ENTITY})


async def golden_evaluation(
    make_harness: HarnessFactory,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    *,
    embedder: FakeEmbedder | None = None,
) -> tuple[RetrievalEvaluation, dict[str, list[uuid.UUID]]]:
    """Build the golden store, index it when an embedder is given, and ask every question.
    Returns the evaluation and the stored memories' ids by content."""
    golden = require_golden_cases()
    cases = load_retrieval_cases()
    check_against_golden(cases, golden)
    harness = make_harness(GoldenFixtureExtractor(golden), timezone_name=TIMEZONE_NAME)
    await build_golden_store(harness.ingestion, harness.runner, golden)
    if embedder is not None:
        report = await MemoryIndexer(session_factory, embedder, clock=clock).run()
        assert report.stopped_by is None
    index = await memories_by_content(session_factory)
    evaluation = await evaluate(
        engine(session_factory, clock, embedder=embedder), cases, golden, index
    )
    return evaluation, index


def of(evaluation: RetrievalEvaluation, *categories: QueryCategory) -> list[QueryResult]:
    results = [result for result in evaluation.results if result.case.category in categories]
    assert results, f"the question set has no {categories} questions"
    return results


def below_one(results: Sequence[QueryResult], metric: str) -> list[str]:
    """The questions that fall short on ``metric``, readable in a failure message."""
    return [
        f"{result.case.query_id} {result.case.query!r}: {metric}={result.metrics[metric]:.2f}"
        for result in results
        if result.metrics[metric] < 1.0
    ]


async def test_words_and_names_answer_every_keyword_and_name_question(
    make_harness: HarnessFactory,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    evaluation, index = await golden_evaluation(make_harness, session_factory, clock)

    exact = of(evaluation, *EXACT)
    assert below_one(exact, "hit@5") == []
    assert below_one(exact, "recall@10") == []
    # Nothing stored is about these, and nothing comes back.
    assert below_one(of(evaluation, QueryCategory.NEGATIVE), "clean") == []
    # Words and names only, as configured: nothing is degraded.
    assert evaluation.embedding_space is None
    assert not any(result.degraded for result in evaluation.results)

    summary = evaluation.summary()
    assert set(summary) == {category.value for category in QueryCategory} | {"all"}
    contents = {memory_id: content for content, ids in index.items() for memory_id in ids}
    report = render_markdown(evaluation, contents)
    assert report.startswith("# Retrieval evaluation")
    for category in QueryCategory:
        assert f"| {category.value} |" in report
    # Every question that missed an answer is listed, so a regression is easy to read.
    for result in evaluation.results:
        if result.missed:
            assert f"**{result.case.query_id}**" in report


async def test_adding_meaning_never_buries_a_word_or_name_match(
    make_harness: HarnessFactory,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    embedder = FakeEmbedder()

    evaluation, index = await golden_evaluation(
        make_harness, session_factory, clock, embedder=embedder
    )

    assert below_one(of(evaluation, *EXACT), "recall@10") == []
    assert evaluation.embedding_space == embedder.space.key
    assert not any(result.degraded for result in evaluation.results)
    # Each stored memory was embedded once as a document, except sensitive ones, which are
    # never sent to the provider; each question was embedded once as a query.
    documents = [call for call in embedder.calls if call.input_type is EmbeddingInputType.DOCUMENT]
    queries = [call for call in embedder.calls if call.input_type is EmbeddingInputType.QUERY]
    async with session_factory() as session:
        sensitive = await session.scalar(
            select(func.count()).select_from(Memory).where(is_sensitive())
        )
    assert sensitive, "the golden set should hold a sensitive memory"
    assert sum(len(call.texts) for call in documents) == (
        sum(len(ids) for ids in index.values()) - sensitive
    )
    assert len(queries) == len(evaluation.results)
