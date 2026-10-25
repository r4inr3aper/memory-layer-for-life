"""The boundary between retrieval and the providers that turn text into vectors and rank
documents against a query.

Retrieval depends on these protocols only. A provider's identity is part of the data: an
``EmbeddingSpace`` names the provider, model, and dimensions that made a vector, and
vectors are only ever compared within one space. Changing the model therefore never mixes
incompatible vectors; it starts a new space, which is filled by re-embedding.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.integrations.llm_calls import LlmCallContext


class EmbeddingInputType(StrEnum):
    """Retrieval models embed what is stored and what is asked slightly differently."""

    DOCUMENT = "document"
    QUERY = "query"


@dataclass(frozen=True, slots=True)
class EmbeddingSpace:
    provider: str
    model: str
    dimensions: int

    def __post_init__(self) -> None:
        if self.dimensions < 1:
            raise ValueError("An embedding space has at least one dimension.")

    @property
    def key(self) -> str:
        """The stored identity of the space, e.g. ``voyage/voyage-4/1024``."""
        return f"{self.provider}/{self.model}/{self.dimensions}"


@dataclass(frozen=True, slots=True)
class Embeddings:
    """One vector per input text, in input order, and what the call was billed."""

    vectors: tuple[tuple[float, ...], ...]
    total_tokens: int


class Embedder(Protocol):
    @property
    def space(self) -> EmbeddingSpace: ...

    async def embed(
        self,
        texts: Sequence[str],
        *,
        input_type: EmbeddingInputType,
        context: LlmCallContext,
    ) -> Embeddings:
        """Embed the texts. Raises ``IntegrationError`` when the provider fails."""
        ...


@dataclass(frozen=True, slots=True)
class RerankScore:
    """A document's relevance to the query; ``index`` is its position in the input."""

    index: int
    score: float


class Reranker(Protocol):
    @property
    def model(self) -> str: ...

    async def rerank(
        self, query: str, documents: Sequence[str], *, context: LlmCallContext
    ) -> list[RerankScore]:
        """Score every document against the query, best first. Raises
        ``IntegrationError`` when the provider fails."""
        ...
