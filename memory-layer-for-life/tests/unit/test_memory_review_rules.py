"""When two memories are shown together for review, and which changes each state allows."""

import pytest

from app.domain.enums import MemoryStatus, SuggestionKind
from app.domain.errors import MemoryStateError
from app.domain.memory_review import (
    PairSignals,
    classify,
    ensure_can_restore,
    ensure_live,
    numbers_in,
    strength,
)


def signals(
    *,
    same_type: bool = True,
    shared_entities: int = 0,
    identical_text: bool = False,
    text: float = 0.0,
    meaning: float | None = None,
    numbers_a: tuple[str, ...] = (),
    numbers_b: tuple[str, ...] = (),
) -> PairSignals:
    return PairSignals(
        same_type=same_type,
        shared_entities=shared_entities,
        identical_text=identical_text,
        text_similarity=text,
        meaning_similarity=meaning,
        numbers_a=numbers_a,
        numbers_b=numbers_b,
    )


# --- Duplicates ------------------------------------------------------------------------


def test_the_same_text_twice_is_a_duplicate() -> None:
    assert classify(signals(identical_text=True, text=1.0)) is SuggestionKind.DUPLICATE


def test_nearly_the_same_text_is_a_duplicate() -> None:
    assert classify(signals(text=0.85)) is SuggestionKind.DUPLICATE


def test_the_same_meaning_in_other_words_is_a_duplicate() -> None:
    assert classify(signals(text=0.4, meaning=0.95)) is SuggestionKind.DUPLICATE


def test_memories_of_different_kinds_are_never_duplicates() -> None:
    # A plan and the event that happened can read alike; neither replaces the other.
    alike = signals(same_type=False, text=0.9)

    assert classify(alike) is None
    assert classify(signals(same_type=False, text=0.9, shared_entities=1)) is (
        SuggestionKind.CONFLICT
    )


# --- Conflicts -------------------------------------------------------------------------


def test_alike_text_with_different_numbers_is_a_conflict_not_a_duplicate() -> None:
    """ "Raju owes me 500" and "Raju owes me 700"."""
    owed = signals(text=0.82, numbers_a=("500",), numbers_b=("700",))

    assert classify(owed) is SuggestionKind.CONFLICT


def test_related_memories_about_the_same_person_may_conflict() -> None:
    assert classify(signals(text=0.4, shared_entities=1)) is SuggestionKind.CONFLICT
    assert classify(signals(text=0.1, meaning=0.85, shared_entities=2)) is (SuggestionKind.CONFLICT)


def test_related_memories_about_nobody_in_common_are_not_suggested() -> None:
    assert classify(signals(text=0.5)) is None
    assert classify(signals(text=0.2, meaning=0.85)) is None


def test_unrelated_memories_are_not_suggested_even_about_the_same_person() -> None:
    assert classify(signals(text=0.2, meaning=0.5, shared_entities=1)) is None
    assert classify(signals(text=0.2, shared_entities=1)) is None


def test_a_missing_embedding_counts_as_unknown_not_as_unrelated() -> None:
    assert classify(signals(text=0.9, meaning=None)) is SuggestionKind.DUPLICATE


# --- Numbers and strength --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Raju owes me 500", {"500"}),
        ("Paid 1,200 on 12.5 litres", {"1200", "125"}),
        ("Rent is 25000, due on the 5th", {"25000", "5"}),
        ("No numbers here", set()),
        ("मुझे 300 रुपये देने हैं", {"300"}),
    ],
)
def test_numbers_are_read_without_separators(text: str, expected: set[str]) -> None:
    assert numbers_in(text) == expected


def test_1200_and_1_200_are_one_number() -> None:
    assert numbers_in("1,200") == numbers_in("1200")


def test_strength_is_the_stronger_signal() -> None:
    assert strength(signals(text=0.4, meaning=0.9)) == 0.9
    assert strength(signals(text=0.85, meaning=None)) == 0.85
    assert strength(signals(identical_text=True, text=0.99)) == 1.0


# --- Lifecycle -------------------------------------------------------------------------


@pytest.mark.parametrize("status", [MemoryStatus.PROPOSED, MemoryStatus.ACTIVE])
def test_live_memories_can_be_changed(status: MemoryStatus) -> None:
    ensure_live(status)


def test_a_replaced_version_cannot_be_changed() -> None:
    with pytest.raises(MemoryStateError, match="newer version"):
        ensure_live(MemoryStatus.SUPERSEDED)


def test_a_retracted_memory_must_be_restored_before_it_changes() -> None:
    with pytest.raises(MemoryStateError, match="Restore it"):
        ensure_live(MemoryStatus.RETRACTED)


def test_only_a_replaced_version_cannot_be_restored() -> None:
    for status in (MemoryStatus.PROPOSED, MemoryStatus.ACTIVE, MemoryStatus.RETRACTED):
        ensure_can_restore(status)
    with pytest.raises(MemoryStateError):
        ensure_can_restore(MemoryStatus.SUPERSEDED)
