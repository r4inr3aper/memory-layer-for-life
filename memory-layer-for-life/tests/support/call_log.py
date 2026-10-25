"""Test doubles around the model call log.

``LoggedScriptedExtractor`` answers from a script like ``ScriptedExtractor`` and reports
each call to an observer the way the real adapter does, so the pipeline's and the
console's call logging can be exercised without a provider.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from app.domain.enums import LlmCallOrigin, LlmCallStatus, LlmOperation
from app.integrations.anthropic_calls import AnthropicCallObserver
from app.integrations.extraction.base import (
    ExtractionRequest,
    ExtractionResponse,
    ExtractionUsage,
)
from app.integrations.llm_calls import (
    UNATTRIBUTED_CALL,
    LlmCallContext,
    LlmCallRecord,
    LlmCallSpec,
)
from app.schemas.extraction import ExtractionOutput
from tests.support.extraction import DEFAULT_DESCRIPTOR, ScriptedExtractor

if TYPE_CHECKING:
    from app.domain.errors import DomainError

T0 = datetime(2026, 10, 11, 23, 0, tzinfo=UTC)


def fake_message(response: ExtractionResponse) -> Any:
    """The provider answer behind a scripted response, as the observer reads it."""
    usage = response.usage or ExtractionUsage()
    return SimpleNamespace(
        model=response.model,
        stop_reason=response.stop_reason or "end_turn",
        _request_id=response.request_id,
        usage=SimpleNamespace(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
        ),
    )


class LoggedScriptedExtractor(ScriptedExtractor):
    def __init__(
        self, observer: AnthropicCallObserver, *script: ExtractionOutput | Exception
    ) -> None:
        super().__init__(*script, descriptor=DEFAULT_DESCRIPTOR)
        self._observer = observer

    async def extract(self, request: ExtractionRequest) -> ExtractionResponse:
        spec = LlmCallSpec(
            provider=self.descriptor.provider,
            operation=LlmOperation.EXTRACTION,
            requested_model=self.descriptor.model or "test-model",
            prompt_version=self.descriptor.prompt_version,
            context=request.call_context or UNATTRIBUTED_CALL,
        )
        async with self._observer.observe(spec) as call:
            response = await super().extract(request)
            call.answered(fake_message(response))
            return response


class FakeProviderCheck:
    """A connection check that remembers which model it was asked about."""

    def __init__(self) -> None:
        self.models: list[str] = []
        self.failure: DomainError | None = None

    async def run(self, model: str) -> None:
        self.models.append(model)
        if self.failure is not None:
            raise self.failure


def make_record(
    *,
    origin: LlmCallOrigin = LlmCallOrigin.OTHER,
    operation: LlmOperation = LlmOperation.EXTRACTION,
    model: str = "claude-haiku-5-5",
    response_model: str | None = None,
    status: LlmCallStatus = LlmCallStatus.SUCCEEDED,
    started_at: datetime = T0,
    duration_ms: int = 100,
    input_tokens: int = 10_000,
    output_tokens: int = 1_000,
    error_code: str | None = None,
    links: dict[str, Any] | None = None,
) -> LlmCallRecord:
    """A finished call, as the observer would report it."""
    if status is LlmCallStatus.FAILED and error_code is None:
        error_code = "EXTRACTION_TRANSIENT_FAILURE"
    return LlmCallRecord(
        spec=LlmCallSpec(
            provider="anthropic",
            operation=operation,
            requested_model=model,
            context=LlmCallContext(origin=origin, **(links or {})),
        ),
        status=status,
        started_at=started_at,
        duration_ms=duration_ms,
        response_model=response_model,
        stop_reason="end_turn" if status is LlmCallStatus.SUCCEEDED else None,
        error_code=error_code,
        error_message="It failed." if error_code is not None else None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
