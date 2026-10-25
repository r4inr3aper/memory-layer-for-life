"""Rules for reviewing memories that need no database: which changes each lifecycle state
allows, and when two memories are worth showing together.

The pipeline saves every memory as ``proposed``. Its owner reviews it:

* accept it (``active``), or retract it as wrong (``retracted``, kept as history but never
  used again), and restore a retracted one;
* correct its text, which makes a new ``active`` version that supersedes it, so the old
  text and its evidence stay inspectable;
* change its kind or whether it is sensitive, in place;
* merge a duplicate into another memory, or mark one memory as replacing another that is
  out of date; the other becomes ``superseded``.

Superseded memories are history: only deleting them is allowed.

Two memories are suggested for review by how similar their text is (trigram similarity,
always available) and, when embeddings exist, how close their meaning is (cosine
similarity). No model is asked: a suggestion is a prompt for the owner to look, never a
change. Near-identical memories of one kind are *duplicates*. Memories about the same
person or thing that are only partly alike, or that state different numbers, are possible
*conflicts*: "Raju owes me 500" and "Raju owes me 700" are not the same memory.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Final

from app.domain.enums import MemoryStatus, SuggestionKind
from app.domain.errors import MemoryStateError

# Statuses whose memory may still be true: the ones a person reviews and changes.
LIVE_STATUSES: Final = frozenset({MemoryStatus.PROPOSED, MemoryStatus.ACTIVE})

# Trigram similarity (pg_trgm ``similarity``) at or above which two memories of one kind
# say the same thing, and the lowest at which two memories about the same person or thing
# are worth comparing at all.
DUPLICATE_TEXT_SIMILARITY: Final = 0.8
RELATED_TEXT_SIMILARITY: Final = 0.35
# The same for meaning (cosine similarity of embeddings). Model specific, like retrieval's
# threshold; measured on voyage-4 phrasings of one fact.
DUPLICATE_MEANING_SIMILARITY: Final = 0.93
RELATED_MEANING_SIMILARITY: Final = 0.8

_NUMBER: Final = re.compile(r"\d+(?:[.,]\d+)*")


def ensure_live(status: MemoryStatus) -> None:
    """Accepting, editing, correcting, merging, and replacing apply to memories that may
    be true."""
    if status is MemoryStatus.SUPERSEDED:
        raise MemoryStateError(
            "A newer version replaced this memory. Change the newer one instead."
        )
    if status is MemoryStatus.RETRACTED:
        raise MemoryStateError("This memory was marked as wrong. Restore it to change it.")


def ensure_can_restore(status: MemoryStatus) -> None:
    """Restoring brings back a memory marked as wrong; a replaced version stays history."""
    if status is MemoryStatus.SUPERSEDED:
        raise MemoryStateError(
            "A newer version replaced this memory. Change the newer one instead."
        )


def numbers_in(text: str) -> frozenset[str]:
    """The numbers a text states, without separators: "1,200" and "1200" are one number."""
    return frozenset(re.sub(r"[.,]", "", match) for match in _NUMBER.findall(text))


@dataclass(frozen=True, slots=True)
class PairSignals:
    """What is known about two memories considered together."""

    same_type: bool
    shared_entities: int
    identical_text: bool
    text_similarity: float
    # None when either memory has no current embedding.
    meaning_similarity: float | None
    numbers_a: Collection[str]
    numbers_b: Collection[str]


def classify(signals: PairSignals) -> SuggestionKind | None:
    """Whether two live memories should be reviewed together, and why.

    A duplicate is one kind of memory saying the same thing, with the same numbers. A
    conflict is two memories about a shared person or thing that are related but not
    the same, or alike except for their numbers. Anything else is not suggested.
    """
    meaning = signals.meaning_similarity
    same_numbers = set(signals.numbers_a) == set(signals.numbers_b)
    near_identical = (
        signals.identical_text
        or signals.text_similarity >= DUPLICATE_TEXT_SIMILARITY
        or (meaning is not None and meaning >= DUPLICATE_MEANING_SIMILARITY)
    )
    if near_identical and signals.same_type and same_numbers:
        return SuggestionKind.DUPLICATE

    related = (
        near_identical
        or signals.text_similarity >= RELATED_TEXT_SIMILARITY
        or (meaning is not None and meaning >= RELATED_MEANING_SIMILARITY)
    )
    if related and (signals.shared_entities > 0 or (near_identical and not same_numbers)):
        return SuggestionKind.CONFLICT
    return None


def strength(signals: PairSignals) -> float:
    """How alike two memories are, for ordering suggestions: the stronger signal."""
    return max(
        1.0 if signals.identical_text else signals.text_similarity,
        signals.meaning_similarity or 0.0,
    )
