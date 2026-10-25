"""Ranking metrics with binary relevance. ``ranked`` is what the search returned, best
first; ``relevant`` is the set of correct answers."""

import math
import uuid
from collections.abc import Sequence, Set


def recall_at(ranked: Sequence[uuid.UUID], relevant: Set[uuid.UUID], k: int) -> float:
    """Share of the correct answers among the first ``k``."""
    if not relevant:
        raise ValueError("recall needs at least one relevant item")
    return len(_found(ranked[:k], relevant)) / len(relevant)


def precision_at(ranked: Sequence[uuid.UUID], relevant: Set[uuid.UUID], k: int) -> float:
    """Share of the first ``k`` positions holding a correct answer (empty ones count as
    wrong, so returning less is not rewarded)."""
    if k < 1:
        raise ValueError("k must be at least 1")
    return len(_found(ranked[:k], relevant)) / k


def hit_at(ranked: Sequence[uuid.UUID], relevant: Set[uuid.UUID], k: int) -> float:
    """1 when any correct answer is among the first ``k``."""
    return 1.0 if _found(ranked[:k], relevant) else 0.0


def reciprocal_rank(ranked: Sequence[uuid.UUID], relevant: Set[uuid.UUID]) -> float:
    """1 / the rank of the first correct answer; 0 when none was returned."""
    for position, item in enumerate(ranked, start=1):
        if item in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at(ranked: Sequence[uuid.UUID], relevant: Set[uuid.UUID], k: int) -> float:
    """Normalized discounted cumulative gain: correct answers near the top count most,
    scaled so that the best possible order scores 1."""
    if not relevant:
        raise ValueError("nDCG needs at least one relevant item")
    gain = sum(
        1.0 / math.log2(position + 1)
        for position, item in enumerate(ranked[:k], start=1)
        if item in relevant
    )
    ideal = sum(1.0 / math.log2(position + 1) for position in range(1, min(k, len(relevant)) + 1))
    return gain / ideal


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _found(ranked: Sequence[uuid.UUID], relevant: Set[uuid.UUID]) -> set[uuid.UUID]:
    """The distinct relevant items among ``ranked``."""
    return {item for item in ranked if item in relevant}
