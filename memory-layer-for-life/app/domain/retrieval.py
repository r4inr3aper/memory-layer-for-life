"""Retrieval rules that need no database: what a query is, which words it searches for,
and how the rankings of independent signals become one.

Retrieval finds memories through three legs (``RetrievalLeg``): the query's words in a
memory's text, its meaning near the memory's embedding, and the people, places, or things
it names. Each leg ranks its own candidates by its own score. Those scores are not
comparable (a text rank is not a cosine similarity), so they are never mixed: the legs'
*ranks* are combined with reciprocal rank fusion, which needs no calibration and rewards
memories that several legs agree on.

Relevance is not truth. Retrieval only says which memories bear on a question; every
result goes back with the messages it rests on, and the memory's own status says whether
anyone has reviewed it.
"""

import re
import unicodedata
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from app.domain.enums import MemoryStatus, MemoryType, RetrievalLeg
from app.domain.errors import InvalidRetrievalQueryError

MAX_QUERY_CHARS: Final = 500
MAX_RESULTS: Final = 50
# A query is searched for by at most this many of its words.
MAX_LEXICAL_TERMS: Final = 16
# Reciprocal rank fusion's constant, as in the original paper: it damps the advantage of
# the very first ranks so that agreement between legs outweighs one leg's top spot.
DEFAULT_RRF_K: Final = 60

# Memories that may still be true. Superseded and retracted ones are history, not answers.
DEFAULT_STATUSES: Final = frozenset({MemoryStatus.PROPOSED, MemoryStatus.ACTIVE})

_WHITESPACE: Final = re.compile(r"\s+")

# Words that carry no meaning to search for: English function words, and the words people
# use to ask a memory something ("what did I tell you about ...").
STOPWORDS: Final = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "also",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "ever",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "me",
        "more",
        "most",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "whose",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "anything",
        "know",
        "mention",
        "mentioned",
        "memories",
        "memory",
        "please",
        "recall",
        "remember",
        "said",
        "say",
        "something",
        "tell",
        "thing",
        "things",
        "told",
    ]
)


def normalize_query(text: str) -> str:
    """The query as searched: whitespace collapsed, ends trimmed."""
    return _WHITESPACE.sub(" ", text).strip()


def words(text: str) -> Iterator[str]:
    """The words of a text: runs of letters and digits of any script, with the combining
    marks that belong to them (the vowel signs of Devanagari and other Indic scripts are
    marks, not letters). Everything else separates words, including every character with
    a meaning in PostgreSQL's tsquery syntax, so a word is always safe to search for."""
    word: list[str] = []
    for character in text:
        if character.isalnum() or (word and unicodedata.category(character).startswith("M")):
            word.append(character)
        elif word:
            yield "".join(word)
            word = []
    if word:
        yield "".join(word)


def lexical_terms(text: str) -> tuple[str, ...]:
    """The distinct words of a query worth matching, lowercased, in order of appearance.

    One-letter words and stopwords are dropped; numbers are kept, because amounts and
    dates are exactly what people search their notes for.
    """
    terms: list[str] = []
    for term in words(text.lower()):
        if (len(term) < 2 and not term.isdigit()) or term in STOPWORDS or term in terms:
            continue
        terms.append(term)
        if len(terms) == MAX_LEXICAL_TERMS:
            break
    return tuple(terms)


def any_term_tsquery(terms: Sequence[str]) -> str:
    """A tsquery source matching any of the terms.

    Not ``plainto_tsquery`` or ``websearch_to_tsquery``: both require *every* word, so a
    question in plain language ("how much did I spend on petrol") would match almost
    nothing. Requiring any word and ranking by how many match (``ts_rank_cd``) finds the
    memory and still puts the best match first. Terms come from ``lexical_terms``, so they
    hold only letters and digits.
    """
    return " | ".join(terms)


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    """What every leg is restricted to before it ranks, so a filter never starves the
    top of a list.

    ``observed_from`` and ``observed_to`` bound when the memory's fact happened (its
    ``observed_at``, else when it was recorded): from inclusive, to exclusive.

    Sensitive memories are left out unless ``include_sensitive``: a search made for a
    model (the assistant, a scheduled run) never sees them; the owner's own search in the
    app does (ADR-044).
    """

    memory_types: frozenset[MemoryType] | None = None
    statuses: frozenset[MemoryStatus] = DEFAULT_STATUSES
    observed_from: datetime | None = None
    observed_to: datetime | None = None
    # A memory that a later one superseded, or whose validity ended, is left out unless
    # asked for.
    include_superseded: bool = False
    include_expired: bool = False
    include_sensitive: bool = False

    def __post_init__(self) -> None:
        if not self.statuses:
            raise InvalidRetrievalQueryError("At least one memory status must be searched.")
        if self.memory_types is not None and not self.memory_types:
            raise InvalidRetrievalQueryError("At least one memory type must be searched.")
        for moment in (self.observed_from, self.observed_to):
            if moment is not None and moment.tzinfo is None:
                raise InvalidRetrievalQueryError("Time bounds must carry a timezone.")
        if (
            self.observed_from is not None
            and self.observed_to is not None
            and self.observed_from >= self.observed_to
        ):
            raise InvalidRetrievalQueryError("The time range ends before it starts.")


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """One memory search. ``owner_id`` is whose memories are searched; None is the
    operator's own store, never everyone's."""

    text: str
    owner_id: uuid.UUID | None
    limit: int = 10
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)

    def __post_init__(self) -> None:
        normalized = normalize_query(self.text)
        if not normalized:
            raise InvalidRetrievalQueryError("A search needs some text.")
        if len(normalized) > MAX_QUERY_CHARS:
            raise InvalidRetrievalQueryError(
                f"A search can be at most {MAX_QUERY_CHARS} characters long."
            )
        if not 1 <= self.limit <= MAX_RESULTS:
            raise InvalidRetrievalQueryError(f"A search returns 1 to {MAX_RESULTS} results.")
        object.__setattr__(self, "text", normalized)


@dataclass(frozen=True, slots=True)
class LegHit:
    """One leg's verdict on one memory: its 1-based rank in that leg, and the leg's own
    score (a text rank, a cosine similarity, or an entity-name match)."""

    memory_id: uuid.UUID
    rank: int
    score: float


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    memory_id: uuid.UUID
    score: float
    hits: Mapping[RetrievalLeg, LegHit]

    @property
    def best_rank(self) -> int:
        return min(hit.rank for hit in self.hits.values())


def ranked_hits(scored: Sequence[tuple[uuid.UUID, float]]) -> list[LegHit]:
    """Ranks for one leg's scored memories, already ordered best first. A memory listed
    twice keeps its first, better place."""
    hits: list[LegHit] = []
    seen: set[uuid.UUID] = set()
    for memory_id, score in scored:
        if memory_id in seen:
            continue
        seen.add(memory_id)
        hits.append(LegHit(memory_id=memory_id, rank=len(hits) + 1, score=score))
    return hits


def fuse(
    rankings: Mapping[RetrievalLeg, Sequence[LegHit]],
    *,
    weights: Mapping[RetrievalLeg, float] | None = None,
    k: int = DEFAULT_RRF_K,
) -> list[FusedCandidate]:
    """Reciprocal rank fusion: each leg adds ``weight / (k + rank)`` for every memory it
    ranks.

    Ties are broken deterministically: by how many legs found the memory, then by its
    best rank in any leg, then by its id, so the same inputs always give the same order.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    totals: dict[uuid.UUID, float] = {}
    hits: dict[uuid.UUID, dict[RetrievalLeg, LegHit]] = {}
    for leg, leg_hits in rankings.items():
        weight = 1.0 if weights is None else weights.get(leg, 1.0)
        if weight <= 0:
            continue
        for hit in leg_hits:
            memory_hits = hits.setdefault(hit.memory_id, {})
            if leg in memory_hits:
                continue
            memory_hits[leg] = hit
            totals[hit.memory_id] = totals.get(hit.memory_id, 0.0) + weight / (k + hit.rank)
    candidates = [
        FusedCandidate(memory_id=memory_id, score=totals[memory_id], hits=memory_hits)
        for memory_id, memory_hits in hits.items()
    ]
    candidates.sort(
        key=lambda candidate: (
            -candidate.score,
            -len(candidate.hits),
            candidate.best_rank,
            str(candidate.memory_id),
        )
    )
    return candidates
