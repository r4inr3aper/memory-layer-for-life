import uuid
from datetime import datetime
from typing import Any

from pydantic import Field, computed_field, field_validator

from app.core.config import EffortLevel
from app.domain.enums import (
    EvaluationCaseOutcome,
    EvaluationRunStatus,
    EvaluationTrigger,
    ExtractionDisposition,
)
from app.schemas.common import ResponseSchema, StrictSchema


class EvaluationStartRequest(StrictSchema):
    """Which cases to evaluate and with which models.

    An evaluation calls a model twice per case, so it costs money and sends the
    dataset's messages to the provider.
    """

    extractor_model: str | None = Field(
        default=None, description="Defaults to the configured model."
    )
    extraction_effort: EffortLevel | None = None
    judge_model: str | None = Field(default=None, description="Defaults to the extractor model.")
    judge_effort: EffortLevel = "high"
    case_ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
        description="Only these cases. Leave out to run the whole dataset.",
    )
    concurrency: int = Field(default=6, ge=1, le=16)

    @field_validator("case_ids")
    @classmethod
    def case_ids_must_be_distinct(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("case_ids must not repeat a case")
        return value


class EvaluationRunResponse(ResponseSchema):
    id: uuid.UUID
    status: EvaluationRunStatus
    trigger: EvaluationTrigger
    dataset_name: str
    extractor_model: str | None
    extractor_version: str
    extraction_effort: str | None
    judge_model: str | None
    judge_effort: str | None
    judge_prompt_version: str | None
    concurrency: int | None
    cases_total: int
    cases_passed: int
    cases_failed: int
    cases_not_evaluated: int
    check_totals: dict[str, Any]
    not_gating: dict[str, Any]
    usage: dict[str, Any]
    estimated_cost_usd: float | None
    calls_logged: bool = Field(
        description="False for a run imported from a report file: only its totals are known."
    )
    source_report: str | None
    error_message: str | None
    started_at: datetime
    heartbeat_at: datetime
    finished_at: datetime | None
    created_at: datetime

    @computed_field(description="Cases scored or given up on so far.")  # type: ignore[prop-decorator]
    @property
    def cases_done(self) -> int:
        return self.cases_passed + self.cases_failed + self.cases_not_evaluated

    @computed_field(  # type: ignore[prop-decorator]
        description="Passed cases as a share of evaluated cases. Null before any is evaluated."
    )
    @property
    def pass_rate(self) -> float | None:
        evaluated = self.cases_passed + self.cases_failed
        return self.cases_passed / evaluated if evaluated else None


class EvaluationCaseSummaryResponse(ResponseSchema):
    case_id: str
    position: int
    outcome: EvaluationCaseOutcome
    expected_outcome: ExtractionDisposition
    produced_disposition: ExtractionDisposition | None
    failed_checks: list[str]
    error: str | None


class EvaluationCaseDetailResponse(EvaluationCaseSummaryResponse):
    document: dict[str, Any] = Field(
        description=(
            "The whole case: source messages, expected memory, produced output, every "
            "check, and the judge's explanations."
        )
    )


class DatasetCaseResponse(ResponseSchema):
    case_id: str
    expected_outcome: ExtractionDisposition
    tags: list[str]
    message_count: int
    preview: str


class DatasetResponse(ResponseSchema):
    available: bool
    name: str
    problem: str | None = Field(description="Why the dataset cannot be used, when it cannot.")
    case_count: int
    cases: list[DatasetCaseResponse]


class CaseFailureResponse(ResponseSchema):
    case_id: str
    failed: int
    evaluated: int
