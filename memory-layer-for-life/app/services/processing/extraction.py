"""Extraction stage: normalize the unit, call the extractor, check and finalize the answer.

The extractor already returns output that satisfies the contract. This stage adds what
needs the source messages or must not be left to a model:

* Grounding. Every reference the output makes must point at something that exists.
* Arithmetic. When the output states a calculation and its result, the result is
  recomputed. A model can copy ``245+131+200+135`` correctly and still add it up wrong.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.arithmetic import evaluate_arithmetic
from app.domain.enums import MessageSource
from app.domain.errors import InvalidExtractionOutputError
from app.domain.normalization import normalize_message_text
from app.integrations.extraction.base import (
    ExtractionMessage,
    ExtractionRequest,
    ExtractionResponse,
    Extractor,
)
from app.integrations.llm_calls import LlmCallContext
from app.models.raw_message import RawMessage
from app.schemas.extraction import ExtractedMemory, ExtractionOutput

# Amounts are money: two decimals, and differences below half a unit of the last digit
# are not differences.
_AMOUNT_DECIMALS = 2
_AMOUNT_TOLERANCE = 0.005


@dataclass(frozen=True, slots=True)
class FinalizedExtraction:
    """Extraction output that is safe to persist, and what the system changed in it."""

    output: ExtractionOutput
    corrections: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StageResult:
    response: ExtractionResponse
    corrections: tuple[str, ...] = ()


def build_extraction_request(
    messages: Sequence[RawMessage],
    *,
    timezone_name: str,
    call_context: LlmCallContext | None = None,
) -> ExtractionRequest:
    """Build the extractor input from a unit's raw messages.

    Message text is normalized into a working copy. The stored content is untouched.
    Timestamps are converted to the user's timezone, because expressions such as
    "tomorrow" only make sense against local time. A unit of chat messages is a
    conversation with the assistant: its context (the assistant's messages, what the
    assistant saved) comes from the evidence's own metadata, so a replay sees the same.
    """
    timezone = ZoneInfo(timezone_name)
    conversation = bool(messages) and all(
        message.source == MessageSource.APP_CHAT.value for message in messages
    )
    return ExtractionRequest(
        messages=tuple(
            ExtractionMessage(
                index=index,
                text=normalize_message_text(message.content),
                sent_at_local=(
                    message.source_created_at.astimezone(timezone).replace(tzinfo=None)
                    if message.source_created_at is not None
                    else None
                ),
                assistant_before=(
                    _metadata_text(message, ASSISTANT_BEFORE_KEY) if conversation else None
                ),
            )
            for index, message in enumerate(messages)
        ),
        timezone_name=timezone_name,
        call_context=call_context,
        conversation=conversation,
        already_saved=_already_saved(messages) if conversation else (),
    )


def _metadata_text(message: RawMessage, key: str) -> str | None:
    value = (message.metadata_ or {}).get(key)
    return value if isinstance(value, str) and value.strip() else None


def _already_saved(messages: Sequence[RawMessage]) -> tuple[str, ...]:
    value = (messages[0].metadata_ or {}).get(ALREADY_SAVED_KEY)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())


def validate_grounding(output: ExtractionOutput, *, message_count: int) -> None:
    """Reject output whose references do not point into the unit.

    Raises ``InvalidExtractionOutputError``. The message names positions only, never
    content.
    """
    for position, memory in enumerate(output.memories):
        for evidence in memory.evidence:
            if evidence.message_index >= message_count:
                raise InvalidExtractionOutputError(
                    f"Memory {position} cites message {evidence.message_index}, but the unit "
                    f"has {message_count} message(s)."
                )
    for position, mention in enumerate(output.entity_mentions):
        if mention.message_index >= message_count:
            raise InvalidExtractionOutputError(
                f"Entity mention {position} cites message {mention.message_index}, but the "
                f"unit has {message_count} message(s)."
            )


def _recompute_amount(memory: ExtractedMemory) -> ExtractedMemory | None:
    """Return the memory with its amount recomputed, or ``None`` if nothing changes."""
    financial = memory.financial
    if financial is None or financial.calculation is None or financial.amount is None:
        return None
    computed = evaluate_arithmetic(financial.calculation)
    if computed is None:
        return None
    computed = round(computed, _AMOUNT_DECIMALS)
    if math.isclose(financial.amount, computed, abs_tol=_AMOUNT_TOLERANCE):
        return None
    return memory.model_copy(
        update={"financial": financial.model_copy(update={"amount": computed})}
    )


def reconcile_arithmetic(output: ExtractionOutput) -> FinalizedExtraction:
    """Replace stated results of written calculations with computed ones.

    Only an amount the extractor stated is corrected. A missing amount stays missing: the
    extractor leaves it out on purpose when no single amount applies.
    """
    memories = list(output.memories)
    corrections: list[str] = []
    for position, memory in enumerate(memories):
        corrected = _recompute_amount(memory)
        if corrected is not None:
            memories[position] = corrected
            corrections.append(f"memory {position}: amount recomputed from the written calculation")
    if not corrections:
        return FinalizedExtraction(output)
    return FinalizedExtraction(output.model_copy(update={"memories": memories}), tuple(corrections))


def finalize_extraction(output: ExtractionOutput, *, message_count: int) -> FinalizedExtraction:
    """Validate extractor output against its unit and apply system-owned corrections.

    Raises ``InvalidExtractionOutputError`` when the output cannot be used.
    """
    validate_grounding(output, message_count=message_count)
    return reconcile_arithmetic(output)


# Metadata key of a unit's own timezone, set by sources that know it (app chats).
UNIT_TIMEZONE_KEY: Final = "timezone"
# Metadata keys of a chat message's context (ADR-048): the assistant message it answered,
# and, on a unit's first message, what the assistant saved during that conversation.
ASSISTANT_BEFORE_KEY: Final = "assistant_before"
ALREADY_SAVED_KEY: Final = "saved_by_assistant"


def unit_timezone(messages: Sequence[RawMessage]) -> str | None:
    """The timezone the unit's first message was written in, when its source recorded a
    valid one. Part of the stored evidence, so reprocessing gives the same result."""
    if not messages:
        return None
    # Stored messages always carry a dict; one not yet flushed may still hold None.
    name = (messages[0].metadata_ or {}).get(UNIT_TIMEZONE_KEY)
    if not isinstance(name, str) or not name:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return name


class ExtractionStage:
    def __init__(self, extractor: Extractor, *, timezone_name: str) -> None:
        self._extractor = extractor
        self._timezone_name = timezone_name

    async def run(
        self, messages: Sequence[RawMessage], *, call_context: LlmCallContext | None = None
    ) -> StageResult:
        """Extract from the unit. Raises ``ExtractionError`` on any failure.

        ``call_context`` names the run this extraction belongs to, for the call log.
        """
        request = build_extraction_request(
            messages,
            timezone_name=unit_timezone(messages) or self._timezone_name,
            call_context=call_context,
        )
        response = await self._extractor.extract(request)
        finalized = finalize_extraction(response.output, message_count=len(messages))
        return StageResult(
            response=replace(response, output=finalized.output),
            corrections=finalized.corrections,
        )
