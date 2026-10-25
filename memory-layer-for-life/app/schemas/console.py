from datetime import date, datetime

from pydantic import Field

from app.schemas.common import ResponseSchema, StrictSchema
from app.schemas.llm_call import LlmCallResponse


class ModelPricesResponse(ResponseSchema):
    """List prices in US dollars per million tokens."""

    input_usd_per_mtok: float
    output_usd_per_mtok: float
    cache_write_usd_per_mtok: float
    cache_read_usd_per_mtok: float


class ModelOptionResponse(ResponseSchema):
    """A model that can be chosen for a test call or an evaluation."""

    id: str
    display_name: str
    is_default: bool
    supports_refusal_fallback: bool
    prices: ModelPricesResponse | None = Field(description="Null when the price is not known.")


class ConsoleLimitsResponse(ResponseSchema):
    max_unit_messages: int
    max_content_chars: int


class ConsoleConfigResponse(ResponseSchema):
    """What the console needs to know about this deployment. It holds no secret."""

    app_name: str
    environment: str
    provider_configured: bool = Field(description="Whether model calls can be made.")
    default_model: str
    default_effort: str
    default_timezone: str
    effort_levels: list[str]
    models: list[ModelOptionResponse]
    prices_checked_on: date
    prices_source: str
    pipeline: dict[str, str | None] = Field(description="The pipeline fingerprint in use.")
    limits: ConsoleLimitsResponse
    evaluation_running: bool
    dataset_available: bool


class ConnectionCheckRequest(StrictSchema):
    model: str | None = Field(default=None, description="Defaults to the configured model.")


class ConnectionCheckResponse(ResponseSchema):
    ok: bool
    model: str
    error_code: str | None
    error_message: str | None
    call: LlmCallResponse | None = Field(description="The logged call, when it was logged.")


class PipelineStatsResponse(ResponseSchema):
    raw_messages: int
    entities: int
    runs_by_status: dict[str, int]
    extractions_by_disposition: dict[str, int]
    memories_by_type: dict[str, int]
    memories_by_status: dict[str, int]
    mentions_by_resolution: dict[str, int]


class ReportResponse(ResponseSchema):
    slug: str
    title: str
    markdown: str
    updated_at: datetime
