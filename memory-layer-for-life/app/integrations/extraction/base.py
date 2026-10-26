"""Provider-independent extraction interface.

The pipeline depends only on this module. A provider adapter turns an
``ExtractionRequest`` into a validated ``ExtractionOutput`` and reports failures with
the ``ExtractionError`` types of ``app.domain.errors``, so the pipeline never sees a
provider SDK type.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.domain.versions import ExtractorDescriptor
from app.integrations.llm_calls import LlmCallContext
from app.schemas.extraction import ExtractionOutput


@dataclass(frozen=True, slots=True)
class ExtractionMessage:
    """One message of a processing unit, in its normalized working form.

    ``sent_at_local`` is the wall-clock time in the user's timezone, without tzinfo. It is
    ``None`` when the source did not record when the message was written.
    ``assistant_before`` is, in a conversation with the assistant, the assistant message the
    user was answering: context for reading the message, never evidence.
    """

    index: int
    text: str
    sent_at_local: datetime | None
    assistant_before: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    """One processing unit to extract from.

    ``call_context`` says on whose behalf the extraction runs, for the call log. It is
    not part of what is extracted, so it does not take part in equality.

    ``conversation`` marks a unit the user wrote to their assistant, rather than notes to
    themselves or an import (ADR-048). ``already_saved`` lists what the assistant itself
    saved during that conversation (a reminder, say), so it is not extracted twice.
    """

    messages: tuple[ExtractionMessage, ...]
    timezone_name: str | None = None
    conversation: bool = False
    already_saved: tuple[str, ...] = ()
    call_context: LlmCallContext | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class ExtractionUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ExtractionResponse:
    """A validated extraction and facts about the call that produced it.

    ``raw_output`` is the text the model returned, before validation. It is there for
    inspecting the output format and is never persisted by the pipeline.
    """

    output: ExtractionOutput
    model: str | None = None
    usage: ExtractionUsage | None = None
    request_id: str | None = None
    stop_reason: str | None = None
    raw_output: str | None = None


class Extractor(Protocol):
    """Turns one processing unit into a validated extraction output."""

    @property
    def descriptor(self) -> ExtractorDescriptor:
        """Identity of this extractor. It is part of the processing identity."""
        ...

    async def extract(self, request: ExtractionRequest) -> ExtractionResponse:
        """Extract memories from the unit.

        Raises ``ExtractionError``: ``TransientExtractionError`` when a later retry can
        succeed, a permanent subclass otherwise.
        """
        ...
