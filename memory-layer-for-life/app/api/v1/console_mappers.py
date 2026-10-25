"""Translate console service results into API response schemas.

Handlers stay thin: they call a service and hand the result to one of these functions.
"""

from typing import Any, get_args

from app.core.config import EffortLevel, Settings
from app.domain.enums import PlaygroundRunStatus
from app.domain.model_catalog import PRICES_CHECKED_ON, PRICES_SOURCE, find_model
from app.domain.versions import EXTRACTION_SCHEMA_VERSION, PIPELINE_VERSION, PipelineFingerprint
from app.integrations.extraction.anthropic_extractor import provider_output_schema
from app.integrations.extraction.prompt import EXTRACTION_PROMPT_VERSION
from app.models.evaluation import EvaluationCaseResult, EvaluationRun
from app.models.llm_call import LlmCall
from app.models.playground_run import PlaygroundRun
from app.repositories.evaluation_repository import CaseFailureCount
from app.repositories.llm_call_repository import UsageTotals
from app.repositories.pipeline_stats_repository import PipelineStats
from app.schemas.common import Page
from app.schemas.console import (
    ConnectionCheckResponse,
    ConsoleConfigResponse,
    ConsoleLimitsResponse,
    ModelOptionResponse,
    ModelPricesResponse,
    PipelineStatsResponse,
    ReportResponse,
)
from app.schemas.evaluation import (
    CaseFailureResponse,
    DatasetCaseResponse,
    DatasetResponse,
    EvaluationCaseDetailResponse,
    EvaluationCaseSummaryResponse,
    EvaluationRunResponse,
)
from app.schemas.extraction import ExtractionOutput
from app.schemas.llm_call import (
    DailyUsageResponse,
    EarlierEvaluationsResponse,
    ErrorCountResponse,
    LatencyResponse,
    LlmCallResponse,
    UsageGroupResponse,
    UsageSummaryResponse,
    UsageTotalsResponse,
)
from app.schemas.playground import (
    ExtractionContractResponse,
    PlaygroundMessageResponse,
    PlaygroundRunResponse,
    PlaygroundRunSummaryResponse,
)
from app.services.console_queries import UsageSummary
from app.services.diagnostics import ConnectionCheckResult
from app.services.evaluations import DatasetInfo
from app.services.playground import PlaygroundResult, allowed_models
from app.services.queries import PageResult
from app.services.reports import ReportDocument

_PREVIEW_CHARS = 80


# --- Model calls and usage ------------------------------------------------------------


def to_llm_call_response(call: LlmCall) -> LlmCallResponse:
    return LlmCallResponse.model_validate(call)


def to_llm_call_page(
    page: PageResult[LlmCall], *, limit: int, offset: int
) -> Page[LlmCallResponse]:
    return Page[LlmCallResponse](
        items=[to_llm_call_response(call) for call in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


def _totals(totals: UsageTotals) -> dict[str, Any]:
    return UsageTotalsResponse(
        calls=totals.calls,
        failed_calls=totals.failed_calls,
        input_tokens=totals.input_tokens,
        output_tokens=totals.output_tokens,
        cache_read_input_tokens=totals.cache_read_input_tokens,
        cache_creation_input_tokens=totals.cache_creation_input_tokens,
        estimated_cost_usd=float(totals.estimated_cost_usd),
        unpriced_calls=totals.unpriced_calls,
        average_duration_ms=totals.average_duration_ms,
    ).model_dump()


def to_usage_summary_response(summary: UsageSummary, *, timezone_name: str) -> UsageSummaryResponse:
    return UsageSummaryResponse(
        totals=UsageTotalsResponse(**_totals(summary.totals)),
        latency=LatencyResponse.model_validate(summary.latency),
        by_model=[
            UsageGroupResponse(key=model, **_totals(totals)) for model, totals in summary.by_model
        ],
        by_origin=[
            UsageGroupResponse(key=origin.value, **_totals(totals))
            for origin, totals in summary.by_origin
        ],
        by_operation=[
            UsageGroupResponse(key=operation.value, **_totals(totals))
            for operation, totals in summary.by_operation
        ],
        by_day=[
            DailyUsageResponse(day=entry.day, model=entry.model, **_totals(entry.totals))
            for entry in summary.by_day
        ],
        errors=[ErrorCountResponse.model_validate(error) for error in summary.errors],
        earlier_evaluations=EarlierEvaluationsResponse(
            runs=summary.earlier_evaluations.runs,
            estimated_cost_usd=float(summary.earlier_evaluations.estimated_cost_usd),
        ),
        first_day=summary.first_day,
        last_day=summary.last_day,
        timezone=timezone_name,
    )


# --- Test calls -----------------------------------------------------------------------


def to_playground_run_response(result: PlaygroundResult) -> PlaygroundRunResponse:
    run = result.run
    return PlaygroundRunResponse(
        id=run.id,
        status=PlaygroundRunStatus(run.status),
        messages=[PlaygroundMessageResponse.model_validate(message) for message in run.messages],
        timezone_name=run.timezone_name,
        requested_model=run.requested_model,
        effort=run.effort,
        output=run.output,
        raw_output=run.raw_output,
        corrections=list(run.corrections),
        error_code=run.error_code,
        error_message=run.error_message,
        created_at=run.created_at,
        finished_at=run.finished_at,
        call=to_llm_call_response(result.call) if result.call is not None else None,
    )


def to_playground_summary_response(run: PlaygroundRun) -> PlaygroundRunSummaryResponse:
    first = str(run.messages[0].get("text", "")) if run.messages else ""
    return PlaygroundRunSummaryResponse(
        id=run.id,
        status=PlaygroundRunStatus(run.status),
        requested_model=run.requested_model,
        effort=run.effort,
        message_count=len(run.messages),
        preview=first[:_PREVIEW_CHARS],
        error_code=run.error_code,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


def to_playground_page(
    page: PageResult[PlaygroundRun], *, limit: int, offset: int
) -> Page[PlaygroundRunSummaryResponse]:
    return Page[PlaygroundRunSummaryResponse](
        items=[to_playground_summary_response(run) for run in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


def extraction_contract_response() -> ExtractionContractResponse:
    return ExtractionContractResponse(
        schema_version=EXTRACTION_SCHEMA_VERSION,
        prompt_version=EXTRACTION_PROMPT_VERSION,
        pipeline_version=PIPELINE_VERSION,
        output_schema=ExtractionOutput.model_json_schema(),
        provider_schema=provider_output_schema(),
    )


# --- Evaluations ----------------------------------------------------------------------


def to_evaluation_run_response(run: EvaluationRun) -> EvaluationRunResponse:
    return EvaluationRunResponse.model_validate(run)


def to_evaluation_run_page(
    page: PageResult[EvaluationRun], *, limit: int, offset: int
) -> Page[EvaluationRunResponse]:
    return Page[EvaluationRunResponse](
        items=[to_evaluation_run_response(run) for run in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


def to_evaluation_case_summary_response(
    case: EvaluationCaseResult,
) -> EvaluationCaseSummaryResponse:
    return EvaluationCaseSummaryResponse.model_validate(case)


def to_evaluation_case_page(
    page: PageResult[EvaluationCaseResult], *, limit: int, offset: int
) -> Page[EvaluationCaseSummaryResponse]:
    return Page[EvaluationCaseSummaryResponse](
        items=[to_evaluation_case_summary_response(case) for case in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


def to_evaluation_case_detail_response(case: EvaluationCaseResult) -> EvaluationCaseDetailResponse:
    return EvaluationCaseDetailResponse.model_validate(case)


def to_dataset_response(info: DatasetInfo) -> DatasetResponse:
    return DatasetResponse(
        available=info.available,
        name=info.name,
        problem=info.problem,
        case_count=len(info.cases),
        cases=[DatasetCaseResponse.model_validate(case) for case in info.cases],
    )


def to_case_failure_responses(counts: tuple[CaseFailureCount, ...]) -> list[CaseFailureResponse]:
    return [CaseFailureResponse.model_validate(count) for count in counts]


# --- Console --------------------------------------------------------------------------


def _model_options(default_model: str) -> list[ModelOptionResponse]:
    options: list[ModelOptionResponse] = []
    for model_id in allowed_models(default_model):
        spec = find_model(model_id)
        options.append(
            ModelOptionResponse(
                id=model_id,
                display_name=spec.display_name if spec is not None else model_id,
                is_default=model_id == default_model,
                supports_refusal_fallback=(
                    spec.supports_refusal_fallback if spec is not None else False
                ),
                prices=(
                    ModelPricesResponse(
                        input_usd_per_mtok=float(spec.prices.input),
                        output_usd_per_mtok=float(spec.prices.output),
                        cache_write_usd_per_mtok=float(spec.prices.cache_write),
                        cache_read_usd_per_mtok=float(spec.prices.cache_read),
                    )
                    if spec is not None
                    else None
                ),
            )
        )
    return options


def to_console_config_response(
    settings: Settings,
    fingerprint: PipelineFingerprint,
    *,
    provider_configured: bool,
    evaluation_running: bool,
    dataset_available: bool,
) -> ConsoleConfigResponse:
    return ConsoleConfigResponse(
        app_name=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        provider_configured=provider_configured,
        default_model=settings.ANTHROPIC_MODEL,
        default_effort=settings.EXTRACTION_EFFORT,
        default_timezone=settings.DEFAULT_TIMEZONE,
        effort_levels=list(get_args(EffortLevel)),
        models=_model_options(settings.ANTHROPIC_MODEL),
        prices_checked_on=PRICES_CHECKED_ON,
        prices_source=PRICES_SOURCE,
        pipeline=fingerprint.as_dict(),
        limits=ConsoleLimitsResponse(
            max_unit_messages=settings.INGESTION_MAX_UNIT_MESSAGES,
            max_content_chars=settings.INGESTION_MAX_CONTENT_CHARS,
        ),
        evaluation_running=evaluation_running,
        dataset_available=dataset_available,
    )


def to_connection_check_response(result: ConnectionCheckResult) -> ConnectionCheckResponse:
    return ConnectionCheckResponse(
        ok=result.ok,
        model=result.model,
        error_code=result.error_code,
        error_message=result.error_message,
        call=to_llm_call_response(result.call) if result.call is not None else None,
    )


def to_pipeline_stats_response(stats: PipelineStats) -> PipelineStatsResponse:
    return PipelineStatsResponse.model_validate(stats)


def to_report_response(document: ReportDocument) -> ReportResponse:
    return ReportResponse.model_validate(document)
