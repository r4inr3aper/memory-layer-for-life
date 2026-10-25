"""The retrieval evaluation's metrics, and the question set's integrity against the golden
dataset."""

import json
import math
import uuid
from pathlib import Path

import pytest

from evaluation.golden import load_golden_cases
from evaluation.retrieval.dataset import (
    QueryCategory,
    RetrievalDatasetError,
    check_against_golden,
    load_retrieval_cases,
    relevant_summaries,
)
from evaluation.retrieval.metrics import (
    hit_at,
    mean,
    ndcg_at,
    precision_at,
    recall_at,
    reciprocal_rank,
)

A, B, C, D, E = (uuid.UUID(int=number) for number in range(1, 6))

# --- Metrics ---------------------------------------------------------------------------


def test_recall_counts_correct_answers_found_among_the_first_k() -> None:
    assert recall_at([A, C, B], {A, B}, 1) == 0.5
    assert recall_at([A, C, B], {A, B}, 3) == 1.0
    assert recall_at([C, D], {A, B}, 10) == 0.0


def test_a_repeated_result_counts_once() -> None:
    assert recall_at([A, A], {A, B}, 2) == 0.5
    assert precision_at([A, A], {A, B}, 2) == 0.5


def test_precision_counts_empty_positions_as_wrong() -> None:
    assert precision_at([A], {A}, 5) == pytest.approx(0.2)
    assert precision_at([A, B], {A, B}, 2) == 1.0


def test_hit_says_whether_any_answer_is_in_the_first_k() -> None:
    assert hit_at([C, A], {A}, 1) == 0.0
    assert hit_at([C, A], {A}, 2) == 1.0


def test_reciprocal_rank_is_one_over_the_first_correct_position() -> None:
    assert reciprocal_rank([C, D, A], {A, B}) == pytest.approx(1 / 3)
    assert reciprocal_rank([C, D], {A}) == 0.0


def test_ndcg_rewards_answers_near_the_top_and_is_one_for_the_best_order() -> None:
    assert ndcg_at([A, B, C], {A, B}, 3) == pytest.approx(1.0)
    worst_found = (1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert ndcg_at([C, A, B], {A, B}, 3) == pytest.approx(worst_found)
    assert ndcg_at([C, D, E], {A}, 3) == 0.0


def test_metrics_need_something_to_find() -> None:
    with pytest.raises(ValueError):
        recall_at([A], set(), 5)
    with pytest.raises(ValueError):
        ndcg_at([A], set(), 5)
    with pytest.raises(ValueError):
        precision_at([A], {A}, 0)


def test_the_mean_of_nothing_is_unknown() -> None:
    assert mean([]) is None
    assert mean([1.0, 0.0]) == 0.5


# --- The question set ------------------------------------------------------------------


def test_every_question_names_memories_the_golden_dataset_has() -> None:
    golden = load_golden_cases()
    cases = load_retrieval_cases()

    check_against_golden(cases, golden)

    by_id = {case.case_id: case for case in golden}
    for case in cases:
        assert len(relevant_summaries(case, by_id)) == len(case.relevant)


def test_the_question_set_covers_every_kind_of_question() -> None:
    categories = {case.category for case in load_retrieval_cases()}

    assert categories == set(QueryCategory)


def test_golden_summaries_are_unique_so_answers_resolve_to_one_memory_each() -> None:
    summaries = [
        memory.summary for case in load_golden_cases() for memory in case.expected.memories
    ]

    assert len(summaries) == len(set(summaries))


def write(tmp_path: Path, *lines: dict[str, object]) -> Path:
    path = tmp_path / "queries.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return path


def question(**overrides: object) -> dict[str, object]:
    return {
        "query_id": "rq_001",
        "query": "Zepto",
        "category": "keyword",
        "relevant": [{"case_id": "expense_003", "memory_index": 0}],
        "review_status": "draft_needs_human_review",
        "annotation_version": "v0.1",
        **overrides,
    }


@pytest.mark.parametrize(
    "line",
    [
        question(category="negative"),  # a negative question with an answer
        question(relevant=[]),  # an answerable question without one
        question(relevant=[{"case_id": "x", "memory_index": 0}] * 2),  # listed twice
        question(query_id="q1"),  # malformed id
        question(surprise=True),  # unknown field
    ],
)
def test_malformed_questions_are_refused(tmp_path: Path, line: dict[str, object]) -> None:
    with pytest.raises(RetrievalDatasetError):
        load_retrieval_cases(write(tmp_path, line))


def test_a_question_id_is_unique(tmp_path: Path) -> None:
    with pytest.raises(RetrievalDatasetError, match="twice"):
        load_retrieval_cases(write(tmp_path, question(), question(query="KFC")))


@pytest.mark.parametrize(
    "relevant",
    [{"case_id": "no_such_case", "memory_index": 0}, {"case_id": "expense_003", "memory_index": 4}],
)
def test_answers_the_golden_dataset_lacks_are_refused(
    tmp_path: Path, relevant: dict[str, object]
) -> None:
    cases = load_retrieval_cases(write(tmp_path, question(relevant=[relevant])))

    with pytest.raises(RetrievalDatasetError):
        check_against_golden(cases, load_golden_cases())
