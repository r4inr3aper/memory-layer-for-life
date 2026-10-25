"""Observation of calls to the Anthropic API.

Every call the application makes to the provider runs inside
``AnthropicCallObserver.observe``. The observer reports exactly one ``LlmCallRecord``
per call, whether the call succeeded, failed at the provider, was answered with
something unusable, or was cancelled. It also writes one structured log line, so a call
leaves a trace even when the record cannot be stored.

The adapter keeps its own error handling. The observer only watches: it reads the
outcome from the exception that leaves the block, and finds provider details on the
SDK error that caused it.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Final

import anthropic
import structlog
from anthropic.types import Message
from anthropic.types.beta import BetaMessage

from app.core.clock import Clock, utc_now
from app.domain.enums import LlmCallStatus
from app.domain.errors import DomainError
from app.integrations.llm_calls import (
    LlmCallRecord,
    LlmCallRecorder,
    LlmCallSpec,
    NullLlmCallRecorder,
)

logger = structlog.get_logger(__name__)

PROVIDER_NAME: Final = "anthropic"

UNEXPECTED_ERROR_CODE: Final = "UNEXPECTED_ERROR"
CANCELLED_ERROR_CODE: Final = "CANCELLED"
_CANCELLED_MESSAGE: Final = "The call was cancelled before it finished."


class ObservedCall:
    """What is learned about a call while it is in flight."""

    __slots__ = (
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "input_tokens",
        "output_tokens",
        "request_id",
        "response_model",
        "stop_reason",
    )

    def __init__(self) -> None:
        self.response_model: str | None = None
        self.stop_reason: str | None = None
        self.request_id: str | None = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0

    def answered(self, message: Message | BetaMessage, *, request_id: str | None = None) -> None:
        """Note the provider's answer.

        Call this as soon as a response arrives, before interpreting it. A response that
        turns out to be a refusal, truncated, or invalid was still billed, and its
        tokens belong in the record.

        A streamed answer is assembled by the SDK and carries no request id of its own;
        pass the stream's ``request_id`` instead.
        """
        usage = message.usage
        self.response_model = message.model
        self.stop_reason = message.stop_reason
        self.request_id = request_id or getattr(message, "_request_id", None)
        self.input_tokens = usage.input_tokens
        self.output_tokens = usage.output_tokens
        self.cache_read_input_tokens = usage.cache_read_input_tokens or 0
        self.cache_creation_input_tokens = usage.cache_creation_input_tokens or 0


def _provider_error(error: BaseException) -> anthropic.APIError | None:
    """The SDK error behind a failure, whether it was raised directly or wrapped."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, anthropic.APIError):
            return current
        seen.add(id(current))
        current = current.__cause__
    return None


def _describe_failure(error: BaseException) -> tuple[str, str]:
    """The error code and message to store. Never the provider's own text."""
    if isinstance(error, DomainError):
        return error.code, error.message
    return UNEXPECTED_ERROR_CODE, f"Unexpected {type(error).__name__}."


class AnthropicCallObserver:
    """Reports one ``LlmCallRecord`` for each call made inside ``observe``."""

    def __init__(self, recorder: LlmCallRecorder | None = None, *, clock: Clock = utc_now) -> None:
        self._recorder: LlmCallRecorder = recorder or NullLlmCallRecorder()
        self._clock = clock

    @asynccontextmanager
    async def observe(self, spec: LlmCallSpec) -> AsyncIterator[ObservedCall]:
        """Watch one call. The block makes the call and tells the result what it learned."""
        call = ObservedCall()
        started_at = self._clock()
        started = time.perf_counter()
        try:
            yield call
        except asyncio.CancelledError:
            # The task is going away, so the report is shielded from the cancellation.
            await asyncio.shield(
                self._report(
                    spec,
                    call,
                    started_at,
                    started,
                    failure=(CANCELLED_ERROR_CODE, _CANCELLED_MESSAGE),
                )
            )
            raise
        except Exception as error:
            await self._report(
                spec,
                call,
                started_at,
                started,
                failure=_describe_failure(error),
                provider_error=_provider_error(error),
            )
            raise
        else:
            await self._report(spec, call, started_at, started)

    async def _report(
        self,
        spec: LlmCallSpec,
        call: ObservedCall,
        started_at: datetime,
        started: float,
        *,
        failure: tuple[str, str] | None = None,
        provider_error: anthropic.APIError | None = None,
    ) -> None:
        status_error = (
            provider_error if isinstance(provider_error, anthropic.APIStatusError) else None
        )
        record = LlmCallRecord(
            spec=spec,
            status=LlmCallStatus.FAILED if failure is not None else LlmCallStatus.SUCCEEDED,
            started_at=started_at,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            response_model=call.response_model,
            stop_reason=call.stop_reason,
            request_id=call.request_id
            or (status_error.request_id if status_error is not None else None),
            http_status=status_error.status_code if status_error is not None else None,
            provider_error_type=_provider_error_type(provider_error),
            error_code=failure[0] if failure is not None else None,
            error_message=failure[1] if failure is not None else None,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cache_read_input_tokens=call.cache_read_input_tokens,
            cache_creation_input_tokens=call.cache_creation_input_tokens,
        )
        _log(record)
        try:
            await self._recorder.record(record)
        except Exception:
            # A call log that cannot be written must never break the call it describes.
            logger.exception(
                "llm_call_record_failed",
                operation=spec.operation.value,
                origin=spec.context.origin.value,
            )


def _provider_error_type(error: anthropic.APIError | None) -> str | None:
    """The provider's own error type, or the SDK error class when there is none."""
    if error is None:
        return None
    if isinstance(error, anthropic.APIStatusError) and error.type is not None:
        return str(error.type)
    return type(error).__name__


def _log(record: LlmCallRecord) -> None:
    spec = record.spec
    fields = {
        "operation": spec.operation.value,
        "origin": spec.context.origin.value,
        "requested_model": spec.requested_model,
        "response_model": record.response_model,
        "duration_ms": record.duration_ms,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "cache_read_input_tokens": record.cache_read_input_tokens,
        "cache_creation_input_tokens": record.cache_creation_input_tokens,
        "stop_reason": record.stop_reason,
        "request_id": record.request_id,
    }
    if record.status is LlmCallStatus.SUCCEEDED:
        logger.info("llm_call_succeeded", **fields)
        return
    logger.warning(
        "llm_call_failed",
        **fields,
        error_code=record.error_code,
        http_status=record.http_status,
        provider_error_type=record.provider_error_type,
    )
