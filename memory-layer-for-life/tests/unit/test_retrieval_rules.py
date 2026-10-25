"""Retrieval rules without a database: query words, validation, and rank fusion."""

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.enums import MemoryStatus, MemoryType, RetrievalLeg
from app.domain.errors import InvalidRetrievalQueryError
from app.domain.retrieval import (
    MAX_LEXICAL_TERMS,
    MAX_QUERY_CHARS,
    LegHit,
    RetrievalFilters,
    RetrievalQuery,
    any_term_tsquery,
    fuse,
    lexical_terms,
    normalize_query,
    ranked_hits,
)

A, B, C, D = (uuid.UUID(int=number) for number in range(1, 5))

# --- Query words -----------------------------------------------------------------------


def test_question_words_are_dropped_and_meaningful_ones_kept_in_order() -> None:
    assert lexical_terms("What did I tell you about Raju's 2980 rupees?") == (
        "raju",
        "2980",
        "rupees",
    )


def test_words_are_lowercased_and_counted_once() -> None:
    assert lexical_terms("Snyk snyk SNYK issues") == ("snyk", "issues")


def test_one_letter_words_go_but_single_digits_stay() -> None:
    assert lexical_terms("a b 5 x 7 apples") == ("5", "7", "apples")


def test_every_script_counts_as_words() -> None:
    assert lexical_terms("राजू ने पैसे दिए") == ("राजू", "ने", "पैसे", "दिए")


def test_punctuation_never_reaches_the_tsquery() -> None:
    terms = lexical_terms("cypher's query | !logging & (o'reilly):*")

    assert terms == ("cypher", "query", "logging", "reilly")
    assert any_term_tsquery(terms) == "cypher | query | logging | reilly"


def test_a_query_is_searched_by_at_most_sixteen_words() -> None:
    words = " ".join(f"word{number}" for number in range(40))

    assert len(lexical_terms(words)) == MAX_LEXICAL_TERMS


def test_a_query_of_only_stopwords_has_no_terms() -> None:
    assert lexical_terms("what do you remember about me?") == ()


def test_whitespace_is_collapsed() -> None:
    assert normalize_query("  where   is\n my \t sister ") == "where is my sister"


# --- Validation ------------------------------------------------------------------------


def test_a_query_is_normalized_on_creation() -> None:
    query = RetrievalQuery(text="  Priya\n in Pune ", owner_id=None)

    assert query.text == "Priya in Pune"
    assert query.filters.statuses == frozenset({MemoryStatus.PROPOSED, MemoryStatus.ACTIVE})


@pytest.mark.parametrize(
    ("text", "limit"),
    [("   ", 10), ("x" * (MAX_QUERY_CHARS + 1), 10), ("ok", 0), ("ok", 51)],
)
def test_invalid_queries_are_refused(text: str, limit: int) -> None:
    with pytest.raises(InvalidRetrievalQueryError):
        RetrievalQuery(text=text, owner_id=None, limit=limit)


@pytest.mark.parametrize(
    "filters",
    [
        {"statuses": frozenset()},
        {"memory_types": frozenset()},
        {"observed_from": datetime(2026, 1, 1)},  # no timezone
        {
            "observed_from": datetime(2026, 2, 1, tzinfo=UTC),
            "observed_to": datetime(2026, 1, 1, tzinfo=UTC),
        },
    ],
)
def test_contradictory_filters_are_refused(filters: dict[str, object]) -> None:
    with pytest.raises(InvalidRetrievalQueryError):
        RetrievalFilters(**filters)  # type: ignore[arg-type]


def test_valid_filters_are_kept() -> None:
    filters = RetrievalFilters(
        memory_types=frozenset({MemoryType.TASK}),
        observed_from=datetime(2026, 1, 1, tzinfo=UTC),
        observed_to=datetime(2026, 2, 1, tzinfo=UTC),
    )

    assert filters.memory_types == frozenset({MemoryType.TASK})


# --- Fusion ----------------------------------------------------------------------------


def hits(*memory_ids: uuid.UUID) -> list[LegHit]:
    return ranked_hits([(memory_id, 1.0) for memory_id in memory_ids])


def test_ranks_are_given_in_order_and_a_repeated_memory_keeps_its_first_place() -> None:
    assert [(hit.memory_id, hit.rank) for hit in ranked_hits([(A, 0.9), (B, 0.8), (A, 0.1)])] == [
        (A, 1),
        (B, 2),
    ]


def test_fusion_adds_one_over_k_plus_rank_for_each_leg() -> None:
    fused = fuse(
        {RetrievalLeg.LEXICAL: hits(A, B), RetrievalLeg.SEMANTIC: hits(B, C)},
        k=60,
    )

    scores = {candidate.memory_id: candidate.score for candidate in fused}
    assert scores[A] == pytest.approx(1 / 61)
    assert scores[B] == pytest.approx(1 / 62 + 1 / 61)
    assert scores[C] == pytest.approx(1 / 62)
    assert [candidate.memory_id for candidate in fused] == [B, A, C]


def test_agreement_between_legs_beats_one_leg_s_top_spot() -> None:
    fused = fuse(
        {
            RetrievalLeg.LEXICAL: hits(A, B),
            RetrievalLeg.SEMANTIC: hits(C, B),
            RetrievalLeg.ENTITY: hits(D, B),
        }
    )

    assert fused[0].memory_id == B
    assert set(fused[0].hits) == {RetrievalLeg.LEXICAL, RetrievalLeg.SEMANTIC, RetrievalLeg.ENTITY}


def test_weights_scale_a_leg_and_a_zero_weight_ignores_it() -> None:
    fused = fuse(
        {RetrievalLeg.LEXICAL: hits(A), RetrievalLeg.SEMANTIC: hits(B)},
        weights={RetrievalLeg.LEXICAL: 2.0, RetrievalLeg.SEMANTIC: 0.0},
        k=60,
    )

    assert [(candidate.memory_id, candidate.score) for candidate in fused] == [(A, 2 / 61)]


def test_equal_scores_are_ordered_by_legs_then_rank_then_id() -> None:
    fused = fuse({RetrievalLeg.LEXICAL: hits(D), RetrievalLeg.SEMANTIC: hits(C)})

    assert [candidate.memory_id for candidate in fused] == [C, D]


def test_fusion_of_nothing_is_nothing() -> None:
    assert fuse({RetrievalLeg.LEXICAL: [], RetrievalLeg.SEMANTIC: []}) == []


def test_k_must_be_positive() -> None:
    with pytest.raises(ValueError):
        fuse({RetrievalLeg.LEXICAL: hits(A)}, k=0)
