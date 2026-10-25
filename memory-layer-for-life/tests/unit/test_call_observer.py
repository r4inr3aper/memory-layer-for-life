"""The call observer, the log row it produces, and the connection check.

Every path a model call can take must end in exactly one record, and no record may
hold anything but facts about the call.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx2
import pytest
import structlog

from app.domain.enums import LlmCallOrigin, LlmCallStatus, LlmOperation
from app.domain.errors import (
    InvalidExtractionOutputError,
    ProviderNotConfiguredError,
    TransientExtractionError,
)
from app.integrations import anthropic_calls
from app.integrations.anthropic_calls import (
    CANCELLED_ERROR_CODE,
    UNEXPECTED_ERROR_CODE,
    AnthropicCallObserver,
)
from app.integrations.anthropic_client import AnthropicClientManager
from app.integrations.anthropic_errors import (
    BILLING_FAILURE_MESSAGE,
    describe_provider_failure,
)
from app.integrations.anthropic_ping import (
    AnthropicConnectionCheck,
    ProviderBillingError,
    ProviderCheckError,
)
from app.integrations.llm_calls import (
    UNATTRIBUTED_CALL,
    LlmCallContext,
    LlmCallRecord,
    LlmCallSpec,
    NullLlmCallRecorder,
)
from app.services.llm_call_log import to_row

HTTP_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)

SPEC = LlmCallSpec(
    provider="anthropic",
    operation=LlmOperation.EXTRACTION,
    requested_model="claude-sonnet-5-5",
    prompt_version="1",
    effort="medium",
    max_tokens=16000,
    refusal_fallback=True,
    context=LlmCallContext(origin=LlmCallOrigin.PLAYGROUND, playground_run_id=None),
)


@pytest.fixture(autouse=True)
def fresh_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the observer a logger that no earlier test has bound.

    A test that runs the application's lifespan configures structlog to cache loggers. A
    cached logger keeps the processors it was bound with, so ``capture_logs`` in a later
    test would see nothing from it. A new logger makes these tests independent of order.
    """
    monkeypatch.setattr(anthropic_calls, "logger", structlog.get_logger("call-observer-test"))


class RecordingRecorder:
    def __init__(self, *, broken: bool = False) -> None:
        self.records: list[LlmCallRecord] = []
        self._broken = broken

    async def record(self, record: LlmCallRecord) -> None:
        if self._broken:
            raise RuntimeError("the database is away")
        self.records.append(record)


def api_response(
    *, model: str = "claude-sonnet-5-5", stop_reason: str = "end_turn", cache_read: int = 3000
) -> Any:
    return SimpleNamespace(
        model=model,
        stop_reason=stop_reason,
        _request_id="req_123",
        content=[],
        usage=SimpleNamespace(
            input_tokens=120,
            output_tokens=45,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=None,
        ),
    )


def status_error(
    error_type: type[anthropic.APIStatusError], status: int, *, body: Any = None
) -> anthropic.APIStatusError:
    response = httpx2.Response(status, request=HTTP_REQUEST, headers={"request-id": "req_err"})
    return error_type("provider said no", response=response, body=body)


def observer_with(recorder: RecordingRecorder) -> AnthropicCallObserver:
    return AnthropicCallObserver(recorder, clock=lambda: NOW)


# --- The observer ---------------------------------------------------------------------


async def test_a_successful_call_is_recorded_with_its_usage() -> None:
    recorder = RecordingRecorder()

    async with observer_with(recorder).observe(SPEC) as call:
        call.answered(api_response())

    (record,) = recorder.records
    assert record.status is LlmCallStatus.SUCCEEDED
    assert record.spec is SPEC
    assert record.started_at == NOW
    assert record.duration_ms >= 0
    assert (record.response_model, record.stop_reason, record.request_id) == (
        "claude-sonnet-5-5",
        "end_turn",
        "req_123",
    )
    assert (record.input_tokens, record.output_tokens) == (120, 45)
    assert (record.cache_read_input_tokens, record.cache_creation_input_tokens) == (3000, 0)
    assert record.error_code is None
    assert record.http_status is None


async def test_an_answer_the_application_rejects_is_a_failure_that_keeps_its_tokens() -> None:
    """The provider answered and billed the call; only afterwards was it found unusable."""
    recorder = RecordingRecorder()

    with pytest.raises(InvalidExtractionOutputError):
        async with observer_with(recorder).observe(SPEC) as call:
            call.answered(api_response())
            raise InvalidExtractionOutputError("2 validation error(s)", raw_output="{...}")

    (record,) = recorder.records
    assert record.status is LlmCallStatus.FAILED
    assert record.error_code == "EXTRACTION_OUTPUT_INVALID"
    assert record.error_message == "2 validation error(s)"
    assert (record.input_tokens, record.output_tokens) == (120, 45)
    assert record.response_model == "claude-sonnet-5-5"


async def test_a_provider_failure_is_described_from_the_sdk_error_it_wraps() -> None:
    recorder = RecordingRecorder()
    body = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}

    with pytest.raises(TransientExtractionError):
        async with observer_with(recorder).observe(SPEC):
            try:
                raise status_error(anthropic.RateLimitError, 429, body=body)
            except anthropic.RateLimitError as error:
                raise TransientExtractionError("The Anthropic API rate limit was hit.") from error

    (record,) = recorder.records
    assert record.status is LlmCallStatus.FAILED
    assert record.error_code == "EXTRACTION_TRANSIENT_FAILURE"
    assert record.http_status == 429
    assert record.provider_error_type == "rate_limit_error"
    # The request id comes from the failed response when there was no answer.
    assert record.request_id == "req_err"
    assert (record.input_tokens, record.output_tokens) == (0, 0)


async def test_a_connection_failure_names_the_sdk_error_class() -> None:
    recorder = RecordingRecorder()

    with pytest.raises(TransientExtractionError):
        async with observer_with(recorder).observe(SPEC):
            try:
                raise anthropic.APITimeoutError(request=HTTP_REQUEST)
            except anthropic.APIConnectionError as error:
                raise TransientExtractionError("The Anthropic API request timed out.") from error

    (record,) = recorder.records
    assert record.provider_error_type == "APITimeoutError"
    assert record.http_status is None


async def test_an_unexpected_error_is_recorded_without_its_message() -> None:
    """Arbitrary exception text can quote anything, so only the type is kept."""
    recorder = RecordingRecorder()

    with pytest.raises(ValueError):
        async with observer_with(recorder).observe(SPEC):
            raise ValueError("the note said: buy milk")

    (record,) = recorder.records
    assert record.error_code == UNEXPECTED_ERROR_CODE
    assert record.error_message == "Unexpected ValueError."
    assert "milk" not in record.error_message


async def test_a_cancelled_call_is_recorded_and_the_cancellation_continues() -> None:
    recorder = RecordingRecorder()
    observer = observer_with(recorder)

    async def call_that_hangs() -> None:
        async with observer.observe(SPEC):
            await asyncio.sleep(60)

    task = asyncio.create_task(call_that_hangs())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    (record,) = recorder.records
    assert record.status is LlmCallStatus.FAILED
    assert record.error_code == CANCELLED_ERROR_CODE


async def test_a_recorder_that_fails_never_breaks_the_call() -> None:
    observer = observer_with(RecordingRecorder(broken=True))

    with structlog.testing.capture_logs() as logs:
        async with observer.observe(SPEC) as call:
            call.answered(api_response())

    events = [entry["event"] for entry in logs]
    assert "llm_call_succeeded" in events
    assert "llm_call_record_failed" in events


async def test_the_observer_logs_facts_and_never_content() -> None:
    with structlog.testing.capture_logs() as logs:
        async with observer_with(RecordingRecorder()).observe(SPEC) as call:
            call.answered(api_response())

    (entry,) = [entry for entry in logs if entry["event"] == "llm_call_succeeded"]
    assert entry["operation"] == "extraction"
    assert entry["origin"] == "playground"
    assert entry["requested_model"] == "claude-sonnet-5-5"
    assert entry["output_tokens"] == 45
    assert "prompt" not in entry
    assert "text" not in entry


async def test_the_default_recorder_keeps_nothing() -> None:
    observer = AnthropicCallObserver()

    async with observer.observe(SPEC) as call:
        call.answered(api_response())

    assert isinstance(observer._recorder, NullLlmCallRecorder)


def test_the_billed_model_is_the_one_that_answered() -> None:
    answered = LlmCallRecord(
        spec=SPEC,
        status=LlmCallStatus.SUCCEEDED,
        started_at=NOW,
        duration_ms=10,
        response_model="claude-opus-4-8",
    )
    unanswered = LlmCallRecord(
        spec=SPEC, status=LlmCallStatus.FAILED, started_at=NOW, duration_ms=10, error_code="X"
    )

    assert answered.billed_model == "claude-opus-4-8"
    assert unanswered.billed_model == "claude-sonnet-5-5"


# --- The log row ----------------------------------------------------------------------


def test_the_row_prices_the_call_by_the_model_that_served_it() -> None:
    """After a refusal fallback the answer comes from, and is billed to, another model."""
    record = LlmCallRecord(
        spec=SPEC,
        status=LlmCallStatus.SUCCEEDED,
        started_at=NOW,
        duration_ms=1234,
        response_model="claude-opus-4-8",
        stop_reason="end_turn",
        request_id="req_123",
        input_tokens=1_000_000,
        output_tokens=100_000,
    )

    row = to_row(record)

    assert row.requested_model == "claude-sonnet-5-5"
    assert row.response_model == "claude-opus-4-8"
    # Opus 4.8: 1M input at $5 and 0.1M output at $25.
    assert row.estimated_cost_usd == Decimal("7.500000")
    assert row.status == "succeeded"
    assert row.origin == "playground"
    assert row.operation == "extraction"
    assert row.refusal_fallback is True
    assert row.started_at == NOW
    assert row.duration_ms == 1234


def test_the_row_of_an_unpriced_model_has_no_cost() -> None:
    spec = LlmCallSpec(
        provider="anthropic", operation=LlmOperation.JUDGE, requested_model="some-other-model"
    )
    record = LlmCallRecord(
        spec=spec, status=LlmCallStatus.SUCCEEDED, started_at=NOW, duration_ms=1, input_tokens=5
    )

    row = to_row(record)

    assert row.estimated_cost_usd is None
    assert row.origin == "other"
    assert row.processing_run_id is None


def test_the_row_bounds_the_error_message() -> None:
    record = LlmCallRecord(
        spec=SPEC,
        status=LlmCallStatus.FAILED,
        started_at=NOW,
        duration_ms=1,
        error_code="EXTRACTION_PERMANENT_FAILURE",
        error_message="x" * 5000,
    )

    assert len(to_row(record).error_message or "") == 2000


# --- Provider failures, described ------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "message", "retryable", "billing"),
    [
        pytest.param(
            anthropic.APITimeoutError(request=HTTP_REQUEST),
            "The Anthropic API request timed out.",
            True,
            False,
            id="timeout",
        ),
        pytest.param(
            anthropic.APIConnectionError(message="down", request=HTTP_REQUEST),
            "The Anthropic API could not be reached.",
            True,
            False,
            id="connection",
        ),
        pytest.param(
            status_error(anthropic.RateLimitError, 429),
            "The Anthropic API rate limit was hit.",
            True,
            False,
            id="rate limit",
        ),
        pytest.param(
            status_error(anthropic.AuthenticationError, 401),
            "The Anthropic API rejected the API key.",
            False,
            False,
            id="bad key",
        ),
        pytest.param(
            status_error(anthropic.PermissionDeniedError, 403),
            "The Anthropic API key is not permitted to make this request.",
            False,
            False,
            id="forbidden",
        ),
        pytest.param(
            status_error(anthropic.NotFoundError, 404),
            "The Anthropic model 'claude-sonnet-5-5' is not available.",
            False,
            False,
            id="unknown model",
        ),
        pytest.param(
            status_error(
                anthropic.APIStatusError,
                402,
                body={"type": "error", "error": {"type": "billing_error", "message": "pay"}},
            ),
            BILLING_FAILURE_MESSAGE,
            False,
            True,
            id="billing",
        ),
        pytest.param(
            status_error(anthropic.InternalServerError, 503),
            "The Anthropic API returned a temporary error (HTTP 503).",
            True,
            False,
            id="server error",
        ),
        pytest.param(
            status_error(anthropic.APIStatusError, 409),
            "The Anthropic API returned a temporary error (HTTP 409).",
            True,
            False,
            id="conflict",
        ),
        pytest.param(
            status_error(anthropic.BadRequestError, 400),
            "The Anthropic API rejected the request (HTTP 400).",
            False,
            False,
            id="bad request",
        ),
    ],
)
def test_provider_failures_are_described_in_our_words(
    error: Any, message: str, retryable: bool, billing: bool
) -> None:
    failure = describe_provider_failure(error, model="claude-sonnet-5-5")

    assert failure.message == message
    assert failure.retryable is retryable
    assert failure.billing is billing
    assert "provider said no" not in failure.message


# --- The connection check -------------------------------------------------------------


def check_with(response: Any) -> tuple[AnthropicConnectionCheck, RecordingRecorder, AsyncMock]:
    client = MagicMock()
    client.messages.create = (
        AsyncMock(side_effect=response)
        if isinstance(response, Exception)
        else AsyncMock(return_value=response)
    )
    manager = MagicMock(spec=AnthropicClientManager)
    manager.client = client
    recorder = RecordingRecorder()
    return (
        AnthropicConnectionCheck(manager, observer_with(recorder)),
        recorder,
        client.messages.create,
    )


async def test_a_working_connection_is_logged_as_a_connection_check() -> None:
    check, recorder, create = check_with(api_response(model="claude-haiku-5-5", cache_read=0))

    await check.run("claude-haiku-5-5")

    (record,) = recorder.records
    assert record.spec.operation is LlmOperation.CONNECTION_CHECK
    assert record.spec.context is UNATTRIBUTED_CALL
    assert record.status is LlmCallStatus.SUCCEEDED
    assert create.await_args.kwargs["model"] == "claude-haiku-5-5"
    # Short and cheap: low effort, and no system prompt to cache.
    assert create.await_args.kwargs["output_config"] == {"effort": "low"}
    assert "system" not in create.await_args.kwargs


async def test_an_account_that_cannot_pay_is_named_by_the_check() -> None:
    body = {"type": "error", "error": {"type": "billing_error", "message": "Payment required"}}
    check, recorder, _ = check_with(status_error(anthropic.APIStatusError, 402, body=body))

    with pytest.raises(ProviderBillingError) as raised:
        await check.run("claude-sonnet-5-5")

    assert raised.value.message == BILLING_FAILURE_MESSAGE
    (record,) = recorder.records
    assert record.error_code == "PROVIDER_BILLING"
    assert record.http_status == 402


async def test_a_declined_check_is_a_failure() -> None:
    check, recorder, _ = check_with(api_response(stop_reason="refusal"))

    with pytest.raises(ProviderCheckError, match="declined"):
        await check.run("claude-sonnet-5-5")

    (record,) = recorder.records
    assert record.stop_reason == "refusal"
    assert record.error_code == "PROVIDER_CHECK_FAILED"


async def test_the_check_needs_a_configured_provider() -> None:
    manager = AnthropicClientManager()
    check = AnthropicConnectionCheck(manager, AnthropicCallObserver())

    with pytest.raises(ProviderNotConfiguredError):
        await check.run("claude-sonnet-5-5")
