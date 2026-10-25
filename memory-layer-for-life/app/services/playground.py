"""Single test calls from the console.

A playground run sends one unit to a model and applies the checks the pipeline applies
to an extraction, without storing a raw message, an entity, or a memory. It exists to
answer "what does the model return for this note, and in what format?" cheaply and
safely. What was typed and what came back are kept, so a test can be reopened.

To watch a note travel through the whole pipeline, capture it through the ingestion API
instead.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.core.config import EffortLevel
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import LlmCallOrigin, PlaygroundRunStatus
from app.domain.errors import (
    ExtractionError,
    InvalidExtractionOutputError,
    InvalidProcessingUnitError,
    ProviderNotConfiguredError,
    RecordNotFoundError,
    UnsupportedModelError,
)
from app.domain.model_catalog import selectable_models
from app.domain.normalization import normalize_message_text
from app.integrations.extraction.base import ExtractionMessage, ExtractionRequest
from app.integrations.extraction.factory import ExtractorFactory
from app.integrations.llm_calls import LlmCallContext
from app.models.llm_call import LlmCall
from app.models.playground_run import PlaygroundRun
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.playground_repository import PlaygroundRepository
from app.services.processing.extraction import finalize_extraction

logger = structlog.get_logger(__name__)

UNEXPECTED_ERROR_CODE: Final = "UNEXPECTED_ERROR"


@dataclass(frozen=True, slots=True)
class PlaygroundMessage:
    """One message of a test unit. ``sent_at`` is timezone-aware when given."""

    text: str
    sent_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PlaygroundLimits:
    max_messages: int
    max_content_chars: int


@dataclass(frozen=True, slots=True)
class PlaygroundResult:
    """A test call and the model call it made. The call is absent only if logging failed."""

    run: PlaygroundRun
    call: LlmCall | None


def allowed_models(configured_model: str) -> tuple[str, ...]:
    """Models a test call may use: the offered ones, and whatever is configured."""
    offered = [spec.id for spec in selectable_models()]
    if configured_model not in offered:
        offered.append(configured_model)
    return tuple(offered)


class PlaygroundService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        extractors: ExtractorFactory,
        *,
        default_model: str,
        default_effort: EffortLevel,
        default_timezone: str,
        limits: PlaygroundLimits,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._extractors = extractors
        self._default_model = default_model
        self._default_effort: EffortLevel = default_effort
        self._default_timezone = default_timezone
        self._limits = limits
        self._clock = clock

    @property
    def available(self) -> bool:
        # A test call can be made when a provider is configured.
        return self._extractors.build() is not None

    async def run(
        self,
        messages: Sequence[PlaygroundMessage],
        *,
        model: str | None = None,
        effort: EffortLevel | None = None,
        timezone_name: str | None = None,
    ) -> PlaygroundResult:
        """Make one test call and return what happened.

        A failed model call is a result, not an exception: the returned run has status
        ``failed`` and says why. Only a request that cannot be attempted raises.
        """
        self._check_limits(messages)
        chosen_model = model or self._default_model
        if chosen_model not in allowed_models(self._default_model):
            raise UnsupportedModelError(chosen_model)
        chosen_effort: EffortLevel = effort or self._default_effort
        chosen_timezone = timezone_name or self._default_timezone

        extractor = self._extractors.build(model=chosen_model, effort=chosen_effort)
        if extractor is None:
            raise ProviderNotConfiguredError

        run_id = new_uuid()
        request = self._build_request(messages, chosen_timezone, run_id)
        async with transaction(self._session_factory) as session:
            await PlaygroundRepository(session).add(
                PlaygroundRun(
                    id=run_id,
                    status=PlaygroundRunStatus.RUNNING.value,
                    messages=[
                        {
                            "index": index,
                            "text": message.text,
                            "sent_at": (
                                message.sent_at.isoformat() if message.sent_at is not None else None
                            ),
                        }
                        for index, message in enumerate(messages)
                    ],
                    timezone_name=chosen_timezone,
                    requested_model=chosen_model,
                    effort=chosen_effort,
                    created_at=self._clock(),
                )
            )

        raw_output: str | None = None
        try:
            response = await extractor.extract(request)
            raw_output = response.raw_output
            # The same finalization the pipeline applies before it stores an extraction.
            finalized = finalize_extraction(response.output, message_count=len(messages))
        except InvalidExtractionOutputError as error:
            await self._finish_failed(
                run_id, error.code, error.message, raw_output=raw_output or error.raw_output
            )
        except ExtractionError as error:
            await self._finish_failed(run_id, error.code, error.message, raw_output=raw_output)
        except Exception as error:
            await self._finish_failed(
                run_id,
                UNEXPECTED_ERROR_CODE,
                f"Unexpected {type(error).__name__}.",
                raw_output=raw_output,
            )
            raise
        else:
            await self._finish_succeeded(
                run_id,
                output=finalized.output.model_dump(mode="json"),
                corrections=list(finalized.corrections),
                raw_output=raw_output,
            )
        return await self.get(run_id)

    async def get(self, run_id: uuid.UUID) -> PlaygroundResult:
        async with self._session_factory() as session:
            run = await PlaygroundRepository(session).get(run_id)
            if run is None:
                raise RecordNotFoundError("Playground run", str(run_id))
            call = await LlmCallRepository(session).latest_for_playground_run(run_id)
            return PlaygroundResult(run=run, call=call)

    # --- Helpers -------------------------------------------------------------------

    def _check_limits(self, messages: Sequence[PlaygroundMessage]) -> None:
        limits = self._limits
        if not messages:
            raise InvalidProcessingUnitError("A test call needs at least one message.")
        if len(messages) > limits.max_messages:
            raise InvalidProcessingUnitError(
                f"A test call can hold at most {limits.max_messages} messages."
            )
        if any(not message.text.strip() for message in messages):
            raise InvalidProcessingUnitError("A message must contain something other than spaces.")
        if any(len(message.text) > limits.max_content_chars for message in messages):
            raise InvalidProcessingUnitError(
                f"A message can be at most {limits.max_content_chars} characters long."
            )

    @staticmethod
    def _build_request(
        messages: Sequence[PlaygroundMessage], timezone_name: str, run_id: uuid.UUID
    ) -> ExtractionRequest:
        """Build the extractor input exactly as the pipeline builds it for a stored unit."""
        timezone = ZoneInfo(timezone_name)
        return ExtractionRequest(
            messages=tuple(
                ExtractionMessage(
                    index=index,
                    text=normalize_message_text(message.text),
                    sent_at_local=(
                        message.sent_at.astimezone(timezone).replace(tzinfo=None)
                        if message.sent_at is not None
                        else None
                    ),
                )
                for index, message in enumerate(messages)
            ),
            timezone_name=timezone_name,
            call_context=LlmCallContext(origin=LlmCallOrigin.PLAYGROUND, playground_run_id=run_id),
        )

    async def _finish_succeeded(
        self,
        run_id: uuid.UUID,
        *,
        output: dict[str, Any],
        corrections: list[str],
        raw_output: str | None,
    ) -> None:
        async with transaction(self._session_factory) as session:
            run = await self._existing(session, run_id)
            run.status = PlaygroundRunStatus.SUCCEEDED.value
            run.output = output
            run.corrections = corrections
            run.raw_output = raw_output
            run.finished_at = self._clock()

    async def _finish_failed(
        self, run_id: uuid.UUID, error_code: str, error_message: str, *, raw_output: str | None
    ) -> None:
        async with transaction(self._session_factory) as session:
            run = await self._existing(session, run_id)
            run.status = PlaygroundRunStatus.FAILED.value
            run.error_code = error_code
            run.error_message = error_message
            run.raw_output = raw_output
            run.finished_at = self._clock()
        logger.warning("playground_run_failed", run_id=str(run_id), error_code=error_code)

    @staticmethod
    async def _existing(session: AsyncSession, run_id: uuid.UUID) -> PlaygroundRun:
        run = await PlaygroundRepository(session).get(run_id)
        if run is None:  # pragma: no cover - the row was written at the start of this call
            raise RecordNotFoundError("Playground run", str(run_id))
        return run
