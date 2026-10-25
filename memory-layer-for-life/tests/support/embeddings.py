"""Deterministic stand-ins for the embedding and reranking providers. No network, ever.

``FakeEmbedder`` makes a bag-of-words vector: each word, lightly stemmed, adds to one
dimension chosen by a stable hash, and the vector is normalized. Words declared in one
``concepts`` group share their dimension, standing in for a model knowing that "sibling"
and "sister" mean nearly the same. That is enough to test the semantic *mechanics*
(paraphrases found, thresholds, spaces, staleness) without pretending to measure quality,
which only the real model can show (``scripts/run_retrieval_eval.py``).
"""

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.domain.retrieval import STOPWORDS
from app.integrations.embeddings.base import (
    EmbeddingInputType,
    Embeddings,
    EmbeddingSpace,
    RerankScore,
)
from app.integrations.llm_calls import LlmCallContext

_WORD = re.compile(r"[^\W_]+")


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)]
    return word


@dataclass
class EmbedCall:
    texts: tuple[str, ...]
    input_type: EmbeddingInputType
    context: LlmCallContext


class FakeEmbedder:
    def __init__(
        self,
        *,
        dimensions: int = 256,
        concepts: Sequence[Sequence[str]] = (),
        model: str = "bag-of-words",
        fail_with: Exception | None = None,
    ) -> None:
        self.space = EmbeddingSpace(provider="fake", model=model, dimensions=dimensions)
        self._concept_of = {_stem(word): group[0] for group in concepts for word in group}
        self.fail_with = fail_with
        self.calls: list[EmbedCall] = []

    @property
    def texts_embedded(self) -> list[str]:
        return [text for call in self.calls for text in call.texts]

    async def embed(
        self,
        texts: Sequence[str],
        *,
        input_type: EmbeddingInputType,
        context: LlmCallContext,
    ) -> Embeddings:
        self.calls.append(EmbedCall(tuple(texts), input_type, context))
        if self.fail_with is not None:
            raise self.fail_with
        return Embeddings(
            vectors=tuple(self.vector(text) for text in texts),
            total_tokens=sum(len(text.split()) for text in texts),
        )

    def vector(self, text: str) -> tuple[float, ...]:
        dimensions = self.space.dimensions
        values = [0.0] * dimensions
        for word in _WORD.findall(text.lower()):
            if word in STOPWORDS:
                continue
            key = self._concept_of.get(_stem(word), _stem(word))
            values[int(hashlib.sha256(key.encode()).hexdigest(), 16) % dimensions] += 1.0
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            # A text with no words still needs a direction; a zero vector has none.
            values[-1] = 1.0
            norm = 1.0
        return tuple(value / norm for value in values)


@dataclass
class FakeReranker:
    """Scores a document 1.0 when it contains ``prefer`` (case-insensitive), else 0.1."""

    prefer: str = ""
    fail_with: Exception | None = None
    model: str = "fake-rerank"
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    async def rerank(
        self, query: str, documents: Sequence[str], *, context: LlmCallContext
    ) -> list[RerankScore]:
        self.calls.append((query, tuple(documents)))
        if self.fail_with is not None:
            raise self.fail_with
        scores = [
            RerankScore(
                index=index,
                score=1.0 if self.prefer and self.prefer.lower() in document.lower() else 0.1,
            )
            for index, document in enumerate(documents)
        ]
        return sorted(scores, key=lambda score: (-score.score, score.index))
