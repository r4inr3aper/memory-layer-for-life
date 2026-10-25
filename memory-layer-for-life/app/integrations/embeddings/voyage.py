"""Voyage AI: embeddings and reranking over its REST API.

Anthropic offers no embedding model and recommends Voyage AI. Embeddings of the voyage-4
models share one space, but this client still treats the configured model as the space,
so changing models is always explicit (see ``EmbeddingSpace``).

Every call goes into the call log with its tokens, so retrieval costs appear next to the
assistant's, attributed to the user they were made for. Messages are written here: the
provider's error text can echo the request (a user's memories), so it is never kept.
"""

import math
import time
from collections.abc import Mapping, Sequence
from typing import Any, Final

import httpx
import structlog

from app.core.clock import Clock, utc_now
from app.domain.enums import LlmCallStatus, LlmOperation
from app.domain.errors import IntegrationError
from app.integrations.embeddings.base import (
    EmbeddingInputType,
    Embeddings,
    EmbeddingSpace,
    RerankScore,
)
from app.integrations.llm_calls import (
    LlmCallContext,
    LlmCallRecord,
    LlmCallRecorder,
    LlmCallSpec,
)

logger = structlog.get_logger(__name__)

SERVICE_NAME: Final = "Voyage AI"
PROVIDER: Final = "voyage"
DEFAULT_BASE_URL: Final = "https://api.voyageai.com/v1"
# Voyage accepts up to 1,000 texts per request within a token budget per model; memories
# are short, so this many fit comfortably under every model's budget.
DEFAULT_BATCH_SIZE: Final = 128
_MAX_RERANK_DOCUMENTS: Final = 1000


class VoyageClient:
    """Implements ``Embedder``, and ``Reranker`` when a rerank model is configured."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        embedding_model: str,
        dimensions: int,
        recorder: LlmCallRecorder,
        rerank_model: str | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        base_url: str = DEFAULT_BASE_URL,
        clock: Clock = utc_now,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._http = http
        self._api_key = api_key
        self._space = EmbeddingSpace(
            provider=PROVIDER, model=embedding_model, dimensions=dimensions
        )
        self._rerank_model = rerank_model
        self._recorder = recorder
        self._batch_size = batch_size
        self._base_url = base_url.rstrip("/")
        self._clock = clock

    @property
    def space(self) -> EmbeddingSpace:
        return self._space

    @property
    def model(self) -> str:
        """The rerank model."""
        if self._rerank_model is None:
            raise RuntimeError("No rerank model is configured.")
        return self._rerank_model

    @property
    def can_rerank(self) -> bool:
        return self._rerank_model is not None

    # --- Embeddings ------------------------------------------------------------------

    async def embed(
        self,
        texts: Sequence[str],
        *,
        input_type: EmbeddingInputType,
        context: LlmCallContext,
    ) -> Embeddings:
        vectors: list[tuple[float, ...]] = []
        tokens = 0
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            body = await self._post(
                "/embeddings",
                {
                    "input": batch,
                    "model": self._space.model,
                    "input_type": input_type.value,
                    "output_dimension": self._space.dimensions,
                    "truncation": True,
                },
                operation=LlmOperation.EMBEDDING,
                model=self._space.model,
                context=context,
            )
            vectors.extend(self._vectors(body, expected=len(batch)))
            tokens += _total_tokens(body)
        return Embeddings(vectors=tuple(vectors), total_tokens=tokens)

    def _vectors(self, body: Mapping[str, Any], *, expected: int) -> list[tuple[float, ...]]:
        data = body.get("data")
        if not isinstance(data, list) or len(data) != expected:
            raise IntegrationError(SERVICE_NAME, "returned a different number of embeddings.")
        by_index: dict[int, tuple[float, ...]] = {}
        for item in data:
            index = item.get("index") if isinstance(item, dict) else None
            values = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(index, int) or not isinstance(values, list):
                raise IntegrationError(SERVICE_NAME, "answered with an unexpected shape.")
            try:
                vector = tuple(float(value) for value in values)
            except (TypeError, ValueError) as error:
                raise IntegrationError(
                    SERVICE_NAME, "returned an embedding of non-numbers."
                ) from error
            if len(vector) != self._space.dimensions or not all(map(math.isfinite, vector)):
                raise IntegrationError(
                    SERVICE_NAME,
                    f"returned an embedding that is not {self._space.dimensions} finite numbers.",
                )
            by_index[index] = vector
        if sorted(by_index) != list(range(expected)):
            raise IntegrationError(SERVICE_NAME, "returned embeddings for the wrong inputs.")
        return [by_index[index] for index in range(expected)]

    # --- Reranking -------------------------------------------------------------------

    async def rerank(
        self, query: str, documents: Sequence[str], *, context: LlmCallContext
    ) -> list[RerankScore]:
        if not documents:
            return []
        if len(documents) > _MAX_RERANK_DOCUMENTS:
            raise ValueError(f"At most {_MAX_RERANK_DOCUMENTS} documents can be reranked.")
        model = self.model
        body = await self._post(
            "/rerank",
            {"query": query, "documents": list(documents), "model": model, "truncation": True},
            operation=LlmOperation.RERANK,
            model=model,
            context=context,
        )
        data = body.get("data")
        if not isinstance(data, list):
            raise IntegrationError(SERVICE_NAME, "answered with an unexpected shape.")
        scores: list[RerankScore] = []
        for item in data:
            index = item.get("index") if isinstance(item, dict) else None
            score = item.get("relevance_score") if isinstance(item, dict) else None
            if (
                not isinstance(index, int)
                or not 0 <= index < len(documents)
                or not isinstance(score, int | float)
            ):
                raise IntegrationError(SERVICE_NAME, "answered with an unexpected shape.")
            scores.append(RerankScore(index=index, score=float(score)))
        if sorted(score.index for score in scores) != list(range(len(documents))):
            raise IntegrationError(SERVICE_NAME, "did not score every document once.")
        return sorted(scores, key=lambda score: (-score.score, score.index))

    # --- Transport -------------------------------------------------------------------

    async def _post(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        operation: LlmOperation,
        model: str,
        context: LlmCallContext,
    ) -> dict[str, Any]:
        spec = LlmCallSpec(
            provider=PROVIDER, operation=operation, requested_model=model, context=context
        )
        started_at = self._clock()
        started = time.monotonic()

        def finished(**fields: Any) -> LlmCallRecord:
            return LlmCallRecord(
                spec=spec,
                started_at=started_at,
                duration_ms=max(0, round((time.monotonic() - started) * 1000)),
                **fields,
            )

        try:
            response = await self._http.post(
                f"{self._base_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.HTTPError as error:
            failure = IntegrationError(SERVICE_NAME, "could not be reached.")
            await self._record(
                finished(
                    status=LlmCallStatus.FAILED,
                    error_code=failure.code,
                    error_message=failure.message,
                    provider_error_type=type(error).__name__,
                )
            )
            raise failure from error

        if response.status_code >= 400:
            failure = IntegrationError(SERVICE_NAME, _failure_reason(response.status_code))
            await self._record(
                finished(
                    status=LlmCallStatus.FAILED,
                    http_status=response.status_code,
                    error_code=failure.code,
                    error_message=failure.message,
                    request_id=response.headers.get("request-id"),
                )
            )
            raise failure

        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            failure = IntegrationError(SERVICE_NAME, "answered with an unexpected shape.")
            await self._record(
                finished(
                    status=LlmCallStatus.FAILED,
                    http_status=response.status_code,
                    error_code=failure.code,
                    error_message=failure.message,
                )
            )
            raise failure

        # Billed as soon as it answered, even if the answer turns out unusable.
        await self._record(
            finished(
                status=LlmCallStatus.SUCCEEDED,
                http_status=response.status_code,
                response_model=body.get("model") if isinstance(body.get("model"), str) else None,
                request_id=response.headers.get("request-id"),
                input_tokens=_total_tokens(body),
            )
        )
        return body

    async def _record(self, record: LlmCallRecord) -> None:
        # The call log is bookkeeping: losing a row must never fail a search or an index.
        try:
            await self._recorder.record(record)
        except Exception:
            logger.exception("voyage_call_not_logged", operation=record.spec.operation.value)


def _total_tokens(body: Mapping[str, Any]) -> int:
    usage = body.get("usage")
    tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    return tokens if isinstance(tokens, int) and tokens >= 0 else 0


def _failure_reason(status: int) -> str:
    if status in (401, 403):
        return "rejected VOYAGE_API_KEY."
    if status == 429:
        return "is limiting requests; try again shortly."
    if status >= 500:
        return f"failed (HTTP {status})."
    return f"rejected the request (HTTP {status})."
