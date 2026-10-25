"""A deterministic extractor that answers with what the golden dataset expects.

It lets every golden case run through the real pipeline, with real persistence,
provenance, entity resolution, and idempotency, without calling a model. That is the
fixture layer of the evaluation: it tests the pipeline around the extractor, not the
extractor's judgment.
"""

from collections import defaultdict
from collections.abc import Iterable

from app.domain.enums import (
    EntityType,
    ExtractionDisposition,
    MemoryType,
    Sensitivity,
)
from app.domain.errors import PermanentExtractionError
from app.domain.normalization import locate_span, normalize_message_text
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
from evaluation.golden import GoldenCase, GoldenExpectedMemory
from evaluation.label_mapping import accepted_memory_types, accepted_states

FIXTURE_DESCRIPTOR = ExtractorDescriptor(provider="golden-fixture", model=None, prompt_version="1")

_MAX_QUOTE_LENGTH = 80
_MONEY_ATTRIBUTES = frozenset(
    {"amount", "amounts", "computed_total", "currency", "category", "counterparty", "calculation"}
)

RequestKey = tuple[str, ...]


def request_key(texts: Iterable[str]) -> RequestKey:
    return tuple(texts)


def case_request_key(case: GoldenCase) -> RequestKey:
    return request_key(normalize_message_text(message.content) for message in case.input.messages)


def _quote(text: str) -> str:
    """A verbatim piece of the message: its first line, shortened if long."""
    first_line = text.split("\n", 1)[0].strip()
    return first_line[:_MAX_QUOTE_LENGTH].strip() or text.strip()[:_MAX_QUOTE_LENGTH]


def _financial(expected: GoldenExpectedMemory) -> FinancialInfo | None:
    attributes = expected.attributes
    if not _MONEY_ATTRIBUTES & attributes.keys():
        return None
    amount = attributes.get("amount", attributes.get("computed_total"))
    components = attributes.get("amounts") or ([amount] if amount is not None else [])
    return FinancialInfo(
        amount=float(amount) if amount is not None else None,
        component_amounts=[float(value) for value in components],
        currency=attributes.get("currency"),
        category=attributes.get("category"),
        counterparty=attributes.get("counterparty"),
        calculation=attributes.get("calculation"),
    )


def _temporal(expected: GoldenExpectedMemory) -> TemporalInfo | None:
    expression = expected.attributes.get("date_note")
    if not isinstance(expression, str) or not expression:
        return None
    return TemporalInfo(expression=expression, resolved_date=None)


def _people(expected: GoldenExpectedMemory) -> list[str]:
    attributes = expected.attributes
    names = list(attributes.get("participants") or [])
    counterparty = attributes.get("counterparty")
    if isinstance(counterparty, str):
        names.append(counterparty)
    return list(dict.fromkeys(name for name in names if isinstance(name, str) and name))


def build_expected_output(cases: list[GoldenCase], texts: RequestKey) -> ExtractionOutput:
    """The extraction output the labels of these cases describe for one shared input."""
    first = cases[0]
    if first.expects_abstention:
        return ExtractionOutput(
            disposition=ExtractionDisposition.ABSTAIN,
            disposition_reason=first.expected.rationale,
            memories=[],
            entity_mentions=[],
        )

    mentions: list[ExtractedEntityMention] = []
    memories: list[ExtractedMemory] = []
    for case in cases:
        for expected in case.expected.memories:
            mention_indexes: list[int] = []
            for name in _people(expected):
                # Only names that really occur in a message become mentions.
                for message_index, text in enumerate(texts):
                    span = locate_span(text, name)
                    if span is None:
                        continue
                    mention_indexes.append(len(mentions))
                    mentions.append(
                        ExtractedEntityMention(
                            entity_type=EntityType.PERSON,
                            mention_text=text[span[0] : span[1]],
                            message_index=message_index,
                            confidence=0.9,
                        )
                    )
                    break
            memory_type: MemoryType = accepted_memory_types(expected.type)[0]
            memories.append(
                ExtractedMemory(
                    memory_type=memory_type,
                    content=expected.summary,
                    state=accepted_states(expected.status)[0],
                    confidence=0.9,
                    sensitivity=(
                        Sensitivity.SENSITIVE if expected.has("sensitivity") else Sensitivity.NORMAL
                    ),
                    evidence=[
                        EvidenceReference(message_index=index, quote=_quote(text))
                        for index, text in enumerate(texts)
                    ],
                    ambiguity=expected.attributes.get("ambiguity"),
                    temporal=_temporal(expected),
                    financial=_financial(expected),
                    entity_mention_indexes=mention_indexes,
                )
            )

    return ExtractionOutput(
        disposition=first.expected.outcome,
        disposition_reason=first.expected.rationale,
        memories=memories,
        entity_mentions=mentions,
    )


class GoldenFixtureExtractor:
    """``Extractor`` that returns the expected output for inputs of the golden dataset.

    Cases that share an input are answered together: their expected memories are all
    returned, as an ideal extractor would return them.
    """

    def __init__(self, cases: Iterable[GoldenCase]) -> None:
        self._cases_by_request: dict[RequestKey, list[GoldenCase]] = defaultdict(list)
        for case in cases:
            self._cases_by_request[case_request_key(case)].append(case)
        self.requests: list[ExtractionRequest] = []

    @property
    def descriptor(self) -> ExtractorDescriptor:
        return FIXTURE_DESCRIPTOR

    def cases_for(self, case: GoldenCase) -> list[GoldenCase]:
        """All cases that share this case's input, in dataset order."""
        return self._cases_by_request[case_request_key(case)]

    def expected_output(self, case: GoldenCase) -> ExtractionOutput:
        key = case_request_key(case)
        return build_expected_output(self._cases_by_request[key], key)

    async def extract(self, request: ExtractionRequest) -> ExtractionResponse:
        self.requests.append(request)
        key = request_key(message.text for message in request.messages)
        cases = self._cases_by_request.get(key)
        if not cases:
            raise PermanentExtractionError("The fixture extractor does not know this input.")
        return ExtractionResponse(
            output=build_expected_output(cases, key),
            model=None,
            usage=ExtractionUsage(),
        )
