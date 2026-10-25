"""Golden dataset: typed access to ``golden.jsonl``.

Format facts, established by inspecting the file rather than assumed:

* One JSON object per line, described by ``golden.schema.json``.
* ``timestamp_local`` is ``DD/MM/YY h:mm am|pm`` in the author's local time. The space
  before am/pm is a narrow no-break space. There is no timezone and no seconds.
* Line breaks inside a message are stored as the two characters backslash and ``n``.
* Expected memories use free-form ``type`` and ``status`` labels, plus optional attributes
  that differ per case. ``evaluation.label_mapping`` relates them to the pipeline's
  vocabulary.
* Every case is marked ``draft_needs_human_review``. The labels are a regression baseline,
  not verified ground truth.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ExtractionDisposition
from app.domain.normalization import normalize_message_text
from app.integrations.extraction.base import ExtractionMessage, ExtractionRequest
from app.integrations.llm_calls import LlmCallContext

DEFAULT_DATASET_PATH = Path(__file__).resolve().parent.parent / "golden.jsonl"
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "golden.schema.json"

_TIMESTAMP_FORMAT = "%d/%m/%y %I:%M %p"
_ESCAPED_LINE_BREAK = chr(92) + "n"

ReviewStatus = Literal["draft_needs_human_review", "approved", "rejected"]


class _GoldenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldenMessage(_GoldenModel):
    event_id: str
    source_line: int = Field(ge=1)
    timestamp_local: str
    text: str

    @property
    def content(self) -> str:
        """The message as it was written, with its line breaks restored."""
        return self.text.replace(_ESCAPED_LINE_BREAK, "\n")

    @property
    def sent_at_local(self) -> datetime:
        """Local wall-clock time the message was sent. Carries no timezone."""
        return parse_local_timestamp(self.timestamp_local)


class GoldenInput(_GoldenModel):
    messages: tuple[GoldenMessage, ...] = Field(min_length=1)


class GoldenExpectedMemory(_GoldenModel):
    """One expected memory. ``attributes`` holds every field beyond the three required."""

    type: str
    summary: str
    status: str
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_attributes(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "attributes" in data:
            return data
        core = {key: data[key] for key in ("type", "summary", "status") if key in data}
        extra = {key: value for key, value in data.items() if key not in core}
        return {**core, "attributes": extra}

    def has(self, attribute: str) -> bool:
        """Whether the label states this attribute, even as an explicit null."""
        return attribute in self.attributes


class GoldenExpected(_GoldenModel):
    outcome: ExtractionDisposition
    memories: tuple[GoldenExpectedMemory, ...]
    rationale: str


class GoldenCase(_GoldenModel):
    case_id: str = Field(pattern=r"^[a-z0-9_]+$")
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    input: GoldenInput
    expected: GoldenExpected
    must_not: tuple[str, ...]
    tags: tuple[str, ...]
    review_status: ReviewStatus
    source_fingerprint_sha256: str | None = None
    annotation_version: str | None = None
    dataset_split: str | None = None

    @property
    def expects_abstention(self) -> bool:
        return self.expected.outcome is ExtractionDisposition.ABSTAIN

    @property
    def unit_key(self) -> tuple[str, ...]:
        """Identity of the case's input: the event ids of its messages, in order."""
        return tuple(message.event_id for message in self.input.messages)


class GoldenDatasetError(ValueError):
    """The dataset file is malformed."""


def parse_local_timestamp(value: str) -> datetime:
    """Parse ``DD/MM/YY h:mm am|pm`` into a naive local datetime."""
    cleaned = normalize_message_text(value).upper()
    try:
        return datetime.strptime(cleaned, _TIMESTAMP_FORMAT)
    except ValueError as error:
        raise GoldenDatasetError(f"Unrecognized timestamp format: {value!r}") from error


def load_golden_cases(path: Path = DEFAULT_DATASET_PATH) -> list[GoldenCase]:
    """Read and validate the dataset. Raises ``GoldenDatasetError`` naming the bad line."""
    cases: list[GoldenCase] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as lines:
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                case = GoldenCase.model_validate(json.loads(line))
            except ValueError as error:
                raise GoldenDatasetError(f"{path.name} line {number}: {error}") from error
            if case.case_id in seen:
                raise GoldenDatasetError(
                    f"{path.name} line {number}: duplicate case_id {case.case_id!r}"
                )
            seen.add(case.case_id)
            cases.append(case)
    if not cases:
        raise GoldenDatasetError(f"{path.name} contains no cases")
    return cases


def to_extraction_request(
    case: GoldenCase, *, call_context: LlmCallContext | None = None
) -> ExtractionRequest:
    """Build the extractor input for a case, exactly as the pipeline would build it."""
    return ExtractionRequest(
        messages=tuple(
            ExtractionMessage(
                index=index,
                text=normalize_message_text(message.content),
                sent_at_local=message.sent_at_local,
            )
            for index, message in enumerate(case.input.messages)
        ),
        timezone_name=None,
        call_context=call_context,
    )
