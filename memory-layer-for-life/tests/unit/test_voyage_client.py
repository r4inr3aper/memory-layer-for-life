"""The Voyage AI adapter, against a mock HTTP transport: requests, validation of what
comes back, failures, and the call log."""

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from app.domain.enums import LlmCallOrigin, LlmCallStatus, LlmOperation
from app.domain.errors import IntegrationError
from app.integrations.embeddings.base import EmbeddingInputType
from app.integrations.embeddings.voyage import VoyageClient
from app.integrations.llm_calls import LlmCallContext, LlmCallRecord
from app.services.llm_call_log import to_row

Handler = Callable[[httpx.Request], httpx.Response]
USER = uuid.UUID("6f1c2a43-0d5e-4b8e-9a51-1f0e6a8a2b11")
CONTEXT = LlmCallContext(origin=LlmCallOrigin.INDEXING, user_id=USER)
SECRET_ECHO = "provider says: your memory 'Raju owes 2980' was rejected"


class Recorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.records: list[LlmCallRecord] = []
        self._fail = fail

    async def record(self, record: LlmCallRecord) -> None:
        if self._fail:
            raise RuntimeError("database down")
        self.records.append(record)


def client(
    handler: Handler,
    recorder: Recorder | None = None,
    *,
    dimensions: int = 3,
    batch_size: int = 2,
    rerank_model: str | None = "rerank-2.5-lite",
) -> VoyageClient:
    return VoyageClient(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        api_key="pa_key",
        embedding_model="voyage-4",
        dimensions=dimensions,
        recorder=recorder or Recorder(),
        rerank_model=rerank_model,
        batch_size=batch_size,
        base_url="https://api.voyage.test/v1",
        clock=lambda: datetime(2026, 10, 24, tzinfo=UTC),
    )


def embeddings_response(request: httpx.Request, *, reverse: bool = False) -> httpx.Response:
    body = json.loads(request.content)
    data = [
        {"object": "embedding", "embedding": [float(index), 0.5, -0.5], "index": index}
        for index in range(len(body["input"]))
    ]
    return httpx.Response(
        200,
        json={
            "object": "list",
            "data": list(reversed(data)) if reverse else data,
            "model": "voyage-4",
            "usage": {"total_tokens": 7 * len(body["input"])},
        },
        headers={"request-id": "req_1"},
    )


# --- Embeddings ------------------------------------------------------------------------


async def test_texts_are_embedded_in_batches_in_input_order_with_the_configured_space() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return embeddings_response(request, reverse=True)

    recorder = Recorder()
    result = await client(handler, recorder).embed(
        ["one", "two", "three"], input_type=EmbeddingInputType.DOCUMENT, context=CONTEXT
    )

    assert [json.loads(request.content)["input"] for request in requests] == [
        ["one", "two"],
        ["three"],
    ]
    first = json.loads(requests[0].content)
    assert (first["model"], first["input_type"], first["output_dimension"]) == (
        "voyage-4",
        "document",
        3,
    )
    assert first["truncation"] is True
    assert str(requests[0].url) == "https://api.voyage.test/v1/embeddings"
    assert requests[0].headers["authorization"] == "Bearer pa_key"
    # Answers out of order are put back in input order by their index.
    assert [vector[0] for vector in result.vectors] == [0.0, 1.0, 0.0]
    assert result.total_tokens == 21
    assert len(recorder.records) == 2


async def test_each_call_is_logged_with_its_tokens_and_on_whose_behalf() -> None:
    recorder = Recorder()

    await client(embeddings_response, recorder).embed(
        ["one"], input_type=EmbeddingInputType.QUERY, context=CONTEXT
    )

    [record] = recorder.records
    assert (record.spec.provider, record.spec.operation, record.spec.requested_model) == (
        "voyage",
        LlmOperation.EMBEDDING,
        "voyage-4",
    )
    assert (record.status, record.input_tokens, record.request_id) == (
        LlmCallStatus.SUCCEEDED,
        7,
        "req_1",
    )
    row = to_row(record)
    assert (row.user_id, row.origin, row.operation, row.provider) == (
        USER,
        "indexing",
        "embedding",
        "voyage",
    )
    # Priced from the catalog: voyage-4 is $0.06 per million tokens.
    assert row.estimated_cost_usd is not None


async def test_nothing_to_embed_calls_nothing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    result = await client(handler).embed(
        [], input_type=EmbeddingInputType.DOCUMENT, context=CONTEXT
    )

    assert (result.vectors, result.total_tokens) == ((), 0)


@pytest.mark.parametrize(
    "data",
    [
        [{"embedding": [1.0, 2.0], "index": 0}],  # wrong dimension
        [{"embedding": [1.0, 2.0, "x"], "index": 0}],  # not numbers
        [{"embedding": [1.0, 2.0, 3.0], "index": 5}],  # wrong index
        [],  # missing
        [{"index": 0}],  # no embedding
    ],
)
async def test_unusable_embeddings_are_refused(data: list[object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 1}})

    with pytest.raises(IntegrationError):
        await client(handler).embed(["one"], input_type=EmbeddingInputType.QUERY, context=CONTEXT)


async def test_a_non_finite_embedding_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"data":[{"embedding":[1.0,NaN,0.0],"index":0}],"usage":{"total_tokens":1}}',
            headers={"content-type": "application/json"},
        )

    with pytest.raises(IntegrationError, match="finite"):
        await client(handler).embed(["one"], input_type=EmbeddingInputType.QUERY, context=CONTEXT)


# --- Failures --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "rejected VOYAGE_API_KEY."),
        (403, "rejected VOYAGE_API_KEY."),
        (429, "is limiting requests; try again shortly."),
        (500, "failed (HTTP 500)."),
        (400, "rejected the request (HTTP 400)."),
    ],
)
async def test_provider_errors_are_reported_without_echoing_the_provider(
    status: int, reason: str
) -> None:
    recorder = Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": SECRET_ECHO})

    with pytest.raises(IntegrationError) as raised:
        await client(handler, recorder).embed(
            ["Raju owes 2980"], input_type=EmbeddingInputType.DOCUMENT, context=CONTEXT
        )

    assert raised.value.message == f"Voyage AI: {reason}"
    [record] = recorder.records
    assert (record.status, record.http_status, record.error_code) == (
        LlmCallStatus.FAILED,
        status,
        "INTEGRATION_FAILED",
    )
    assert SECRET_ECHO not in (record.error_message or "")


async def test_an_unreachable_provider_is_logged_and_reported() -> None:
    recorder = Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(IntegrationError, match="could not be reached"):
        await client(handler, recorder).embed(
            ["one"], input_type=EmbeddingInputType.QUERY, context=CONTEXT
        )

    assert recorder.records[0].provider_error_type == "ConnectError"


async def test_a_response_that_is_not_json_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>oops</html>")

    with pytest.raises(IntegrationError, match="unexpected shape"):
        await client(handler).embed(["one"], input_type=EmbeddingInputType.QUERY, context=CONTEXT)


async def test_a_failing_call_log_never_fails_the_call() -> None:
    result = await client(embeddings_response, Recorder(fail=True)).embed(
        ["one"], input_type=EmbeddingInputType.QUERY, context=CONTEXT
    )

    assert len(result.vectors) == 1


# --- Reranking -------------------------------------------------------------------------


async def test_documents_are_reranked_best_first() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                    {"index": 2, "relevance_score": 0.9},
                ],
                "model": "rerank-2.5-lite",
                "usage": {"total_tokens": 30},
            },
        )

    recorder = Recorder()
    scores = await client(handler, recorder).rerank(
        "sister", ["a", "b", "c"], context=LlmCallContext(origin=LlmCallOrigin.RETRIEVAL)
    )

    body = json.loads(requests[0].content)
    assert (body["query"], body["documents"], body["model"]) == (
        "sister",
        ["a", "b", "c"],
        "rerank-2.5-lite",
    )
    assert [(score.index, score.score) for score in scores] == [(1, 0.9), (2, 0.9), (0, 0.2)]
    assert recorder.records[0].spec.operation is LlmOperation.RERANK


@pytest.mark.parametrize(
    "data",
    [
        [{"index": 0, "relevance_score": 0.5}],  # one document unscored
        [{"index": 0, "relevance_score": 0.5}, {"index": 0, "relevance_score": 0.4}],
        [{"index": 7, "relevance_score": 0.5}, {"index": 1, "relevance_score": 0.4}],
        [{"index": 0, "relevance_score": "high"}, {"index": 1, "relevance_score": 0.4}],
    ],
)
async def test_an_incomplete_ranking_is_refused(data: list[object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 1}})

    with pytest.raises(IntegrationError):
        await client(handler).rerank("q", ["a", "b"], context=CONTEXT)


async def test_without_a_rerank_model_there_is_no_reranker() -> None:
    voyage = client(embeddings_response, rerank_model=None)

    assert voyage.can_rerank is False
    with pytest.raises(RuntimeError):
        await voyage.rerank("q", ["a"], context=CONTEXT)


async def test_reranking_nothing_calls_nothing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    assert await client(handler).rerank("q", [], context=CONTEXT) == []
