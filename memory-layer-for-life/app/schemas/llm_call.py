import uuid
from datetime import date, datetime

from pydantic import AwareDatetime, Field

from app.domain.enums import LlmCallOrigin, LlmCallStatus, LlmOperation
from app.schemas.common import ResponseSchema, StrictSchema


class LlmCallFilterParams(StrictSchema):
    """Which calls to list or summarize. Every filter given narrows the selection."""

    origin: LlmCallOrigin | None = None
    operation: LlmOperation | None = None
    status: LlmCallStatus | None = None
    model: str | None = Field(default=None, description="The requested model.")
    processing_run_id: uuid.UUID | None = None
    evaluation_run_id: uuid.UUID | None = None
    playground_run_id: uuid.UUID | None = None
    started_from: AwareDatetime | None = None
    started_before: AwareDatetime | None = None


class LlmCallResponse(ResponseSchema):
    """One logged call to a model provider. Facts about the call, never its content."""

    id: uuid.UUID
    provider: str
    operation: LlmOperation
    origin: LlmCallOrigin
    status: LlmCallStatus
    requested_model: str
    response_model: str | None = Field(
        description="The model that answered. It differs after a refusal fallback."
    )
    prompt_version: str | None
    effort: str | None
    max_tokens: int | None
    refusal_fallback: bool
    stop_reason: str | None
    request_id: str | None
    http_status: int | None
    provider_error_type: str | None
    error_code: str | None
    error_message: str | None
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    estimated_cost_usd: float | None = Field(
        description="Estimate from list prices. Null when the model's price is not known."
    )
    started_at: datetime
    duration_ms: int
    processing_run_id: uuid.UUID | None
    attempt_number: int | None
    evaluation_run_id: uuid.UUID | None
    evaluation_case_id: str | None
    playground_run_id: uuid.UUID | None
    created_at: datetime


class UsageTotalsResponse(ResponseSchema):
    calls: int
    failed_calls: int
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    estimated_cost_usd: float
    unpriced_calls: int = Field(description="Calls that are missing from the cost.")
    average_duration_ms: float | None


class UsageGroupResponse(UsageTotalsResponse):
    key: str


class DailyUsageResponse(UsageTotalsResponse):
    day: date
    model: str


class LatencyResponse(ResponseSchema):
    p50_ms: float | None
    p95_ms: float | None


class ErrorCountResponse(ResponseSchema):
    error_code: str
    calls: int
    last_seen_at: datetime


class EarlierEvaluationsResponse(ResponseSchema):
    """Evaluation runs imported from report files. Their calls are not in the log."""

    runs: int
    estimated_cost_usd: float


class UsageSummaryResponse(ResponseSchema):
    totals: UsageTotalsResponse
    latency: LatencyResponse
    by_model: list[UsageGroupResponse]
    by_origin: list[UsageGroupResponse]
    by_operation: list[UsageGroupResponse]
    by_day: list[DailyUsageResponse]
    errors: list[ErrorCountResponse]
    earlier_evaluations: EarlierEvaluationsResponse
    first_day: date | None
    last_day: date | None
    timezone: str = Field(description="Days are calendar days in this timezone.")
