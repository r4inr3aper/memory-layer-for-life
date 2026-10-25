"""Writes the model call log.

``LlmCallLog`` is the recorder the provider adapters report to. Each record is written
in its own short transaction, separate from whatever the caller is doing: a call that
was made stays logged even when the work around it is rolled back.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.model_catalog import estimate_cost_usd
from app.integrations.llm_calls import LlmCallRecord
from app.models.llm_call import LlmCall
from app.repositories.llm_call_repository import LlmCallRepository

# Stored error messages are sanitized and short. This only guards the column against an
# unexpectedly long one.
_MAX_ERROR_MESSAGE_CHARS = 2000


def to_row(record: LlmCallRecord) -> LlmCall:
    """Turn a finished call into its log row, with the cost estimated from list prices."""
    spec = record.spec
    context = spec.context
    return LlmCall(
        id=new_uuid(),
        provider=spec.provider,
        operation=spec.operation.value,
        origin=context.origin.value,
        status=record.status.value,
        requested_model=spec.requested_model,
        response_model=record.response_model,
        prompt_version=spec.prompt_version,
        effort=spec.effort,
        max_tokens=spec.max_tokens,
        refusal_fallback=spec.refusal_fallback,
        stop_reason=record.stop_reason,
        request_id=record.request_id,
        http_status=record.http_status,
        provider_error_type=record.provider_error_type,
        error_code=record.error_code,
        error_message=(
            record.error_message[:_MAX_ERROR_MESSAGE_CHARS]
            if record.error_message is not None
            else None
        ),
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        cache_read_input_tokens=record.cache_read_input_tokens,
        cache_creation_input_tokens=record.cache_creation_input_tokens,
        estimated_cost_usd=estimate_cost_usd(record.billed_model, record),
        started_at=record.started_at,
        duration_ms=record.duration_ms,
        processing_run_id=context.processing_run_id,
        attempt_number=context.attempt_number,
        evaluation_run_id=context.evaluation_run_id,
        evaluation_case_id=context.evaluation_case_id,
        playground_run_id=context.playground_run_id,
        user_id=context.user_id,
    )


class LlmCallLog:
    """``LlmCallRecorder`` that stores each call in the database."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, record: LlmCallRecord) -> None:
        async with transaction(self._session_factory) as session:
            await LlmCallRepository(session).add(to_row(record))
