"""Builders for extraction output and a scripted extractor.

Tests describe what the extractor returns and the real pipeline does the rest. No test
talks to a model.
"""

from collections.abc import Sequence
from datetime import date

from app.domain.enums import (
    EntityType,
    ExtractionDisposition,
    MemoryState,
    MemoryType,
    Sensitivity,
)
from app.domain.versions import ExtractorDescriptor
from app.integrations.extraction.base import (
    ExtractionRequest,
    ExtractionResponse,
    ExtractionUsage,
)
from app.schemas.extraction import (
    EvidenceReference,
    ExtractedEntityMention,
    ExtractedMemory,
    ExtractionOutput,
    FinancialInfo,
    TemporalInfo,
)

DEFAULT_DESCRIPTOR = ExtractorDescriptor(
    provider="scripted", model="test-model", prompt_version="1"
)


def evidence(message_index: int, quote: str) -> EvidenceReference:
    return EvidenceReference(message_index=message_index, quote=quote)


def memory(
    content: str = "Buy milk",
    *,
    memory_type: MemoryType = MemoryType.TASK,
    state: MemoryState = MemoryState.OPEN,
    evidence_refs: Sequence[EvidenceReference] | None = None,
    mention_indexes: Sequence[int] = (),
    confidence: float = 0.9,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    ambiguity: str | None = None,
    temporal: TemporalInfo | None = None,
    financial: FinancialInfo | None = None,
) -> ExtractedMemory:
    return ExtractedMemory(
        memory_type=memory_type,
        content=content,
        state=state,
        confidence=confidence,
        sensitivity=sensitivity,
        evidence=list(evidence_refs) if evidence_refs is not None else [evidence(0, "buy milk")],
        ambiguity=ambiguity,
        temporal=temporal,
        financial=financial,
        entity_mention_indexes=list(mention_indexes),
    )


def mention(
    text: str,
    *,
    entity_type: EntityType = EntityType.PERSON,
    message_index: int = 0,
    confidence: float = 0.9,
) -> ExtractedEntityMention:
    return ExtractedEntityMention(
        entity_type=entity_type,
        mention_text=text,
        message_index=message_index,
        confidence=confidence,
    )


def financial(
    amount: float | None,
    *,
    component_amounts: Sequence[float] | None = None,
    currency: str | None = None,
    category: str | None = None,
    counterparty: str | None = None,
    calculation: str | None = None,
) -> FinancialInfo:
    if component_amounts is None:
        component_amounts = [amount] if amount is not None else []
    return FinancialInfo(
        amount=amount,
        component_amounts=list(component_amounts),
        currency=currency,
        category=category,
        counterparty=counterparty,
        calculation=calculation,
    )


def temporal(expression: str, resolved_date: date | None = None) -> TemporalInfo:
    return TemporalInfo(expression=expression, resolved_date=resolved_date)


def extraction(
    *memories: ExtractedMemory,
    mentions: Sequence[ExtractedEntityMention] = (),
    disposition: ExtractionDisposition = ExtractionDisposition.EXTRACT,
    reason: str = "The unit states something to remember.",
) -> ExtractionOutput:
    return ExtractionOutput(
        disposition=disposition,
        disposition_reason=reason,
        memories=list(memories) if memories else [memory()],
        entity_mentions=list(mentions),
    )


def abstention(reason: str = "The unit does not say enough.") -> ExtractionOutput:
    return ExtractionOutput(
        disposition=ExtractionDisposition.ABSTAIN,
        disposition_reason=reason,
        memories=[],
        entity_mentions=[],
    )


class ScriptedExtractor:
    """Extractor that answers from a script.

    Each call consumes the next scripted item: an ``ExtractionOutput`` is returned, an
    exception is raised. When the script is exhausted the last item repeats. Every request
    is recorded, so a test can assert how often and with what the pipeline called it.
    """

    def __init__(
        self,
        *script: ExtractionOutput | Exception,
        descriptor: ExtractorDescriptor = DEFAULT_DESCRIPTOR,
    ) -> None:
        self._script: list[ExtractionOutput | Exception] = list(script) or [extraction()]
        self._descriptor = descriptor
        self.requests: list[ExtractionRequest] = []

    @property
    def descriptor(self) -> ExtractorDescriptor:
        return self._descriptor

    def use_script(self, *script: ExtractionOutput | Exception) -> None:
        """Replace the script and forget earlier requests."""
        self._script = list(script) or [extraction()]
        self.requests = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

    async def extract(self, request: ExtractionRequest) -> ExtractionResponse:
        self.requests.append(request)
        position = min(len(self.requests) - 1, len(self._script) - 1)
        item = self._script[position]
        if isinstance(item, Exception):
            raise item
        return ExtractionResponse(
            output=item,
            model=self._descriptor.model,
            usage=ExtractionUsage(input_tokens=100, output_tokens=50),
            request_id=f"req_test_{len(self.requests)}",
        )
