"""Provider-independent description of a model call, for the call log.

Three small values travel through the system:

* ``LlmCallContext`` says on whose behalf a call is made. The caller knows it.
* ``LlmCallSpec`` says what was asked for. The provider adapter knows it.
* ``LlmCallRecord`` adds what happened. The adapter's observer builds it and hands it to
  an ``LlmCallRecorder``.

A record holds facts about a call and never its content: no prompt, no message text, no
model output. What a call was about is found through the run it links to.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.enums import LlmCallOrigin, LlmCallStatus, LlmOperation


@dataclass(frozen=True, slots=True)
class LlmCallContext:
    """Who is making a call. It links the logged call to the run that caused it."""

    origin: LlmCallOrigin
    processing_run_id: uuid.UUID | None = None
    attempt_number: int | None = None
    evaluation_run_id: uuid.UUID | None = None
    evaluation_case_id: str | None = None
    playground_run_id: uuid.UUID | None = None
    # The app user the call is made for, so usage can be counted per user.
    user_id: uuid.UUID | None = None


# Used when a caller gives no context, so that no call goes unlogged.
UNATTRIBUTED_CALL = LlmCallContext(origin=LlmCallOrigin.OTHER)


@dataclass(frozen=True, slots=True)
class LlmCallSpec:
    """What one call asked the provider for."""

    provider: str
    operation: LlmOperation
    requested_model: str
    prompt_version: str | None = None
    effort: str | None = None
    max_tokens: int | None = None
    refusal_fallback: bool = False
    context: LlmCallContext = UNATTRIBUTED_CALL


@dataclass(frozen=True, slots=True)
class LlmCallRecord:
    """One finished call: what was asked, and what happened.

    ``duration_ms`` covers the whole call as the application saw it, including any retry
    the provider SDK made internally. Token counts are zero when the provider never
    answered. A call that was answered and then rejected by the application still
    carries its token counts, because it was billed.
    """

    spec: LlmCallSpec
    status: LlmCallStatus
    started_at: datetime
    duration_ms: int
    response_model: str | None = None
    stop_reason: str | None = None
    request_id: str | None = None
    http_status: int | None = None
    provider_error_type: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def billed_model(self) -> str:
        """The model that answered, which can differ from the one asked for."""
        return self.response_model or self.spec.requested_model


class LlmCallRecorder(Protocol):
    """Receives one record per model call."""

    async def record(self, record: LlmCallRecord) -> None: ...


class NullLlmCallRecorder:
    """Recorder that keeps nothing. For code that runs without a call log."""

    async def record(self, record: LlmCallRecord) -> None:
        return None
