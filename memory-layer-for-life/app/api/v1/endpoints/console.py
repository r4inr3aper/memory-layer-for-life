from fastapi import APIRouter

from app.api.dependencies import (
    ConsoleQueriesDep,
    ContainerDep,
    DiagnosticsServiceDep,
    InsightServiceDep,
)
from app.api.v1.console_mappers import (
    to_connection_check_response,
    to_console_config_response,
    to_pipeline_stats_response,
)
from app.core.exceptions import ErrorResponse
from app.schemas.console import (
    ConnectionCheckRequest,
    ConnectionCheckResponse,
    ConsoleConfigResponse,
    PipelineStatsResponse,
)
from app.schemas.insights import InsightUsefulnessResponse

router = APIRouter()


@router.get(
    "/insights/usefulness",
    response_model=list[InsightUsefulnessResponse],
    summary="How useful app users find each kind of insight",
    description="Feedback across all users, per kind: answers saying useful, and not.",
)
async def insight_usefulness(insights: InsightServiceDep) -> list[InsightUsefulnessResponse]:
    return [
        InsightUsefulnessResponse(kind=row.kind, useful=row.useful, not_useful=row.not_useful)
        for row in await insights.usefulness()
    ]


@router.get(
    "/config",
    response_model=ConsoleConfigResponse,
    summary="Describe this deployment to the console",
    description=(
        "The models that can be chosen with their list prices, the limits, and the "
        "pipeline fingerprint in use. Holds no secret."
    ),
)
async def get_config(container: ContainerDep) -> ConsoleConfigResponse:
    return to_console_config_response(
        container.settings,
        container.fingerprint,
        provider_configured=container.playground_service.available,
        evaluation_running=container.evaluation_service.is_running,
        dataset_available=container.evaluation_service.dataset_available,
    )


@router.post(
    "/connection-check",
    response_model=ConnectionCheckResponse,
    responses={
        422: {"model": ErrorResponse, "description": "The model is not offered"},
        503: {"model": ErrorResponse, "description": "No model provider is configured"},
    },
    summary="Make one tiny model call",
    description=(
        "Proves that the provider can be reached and that the account can pay. It costs "
        "a few tokens and is logged like any other call. A failed call is reported in the "
        "response, not as an error."
    ),
)
async def connection_check(
    payload: ConnectionCheckRequest, diagnostics: DiagnosticsServiceDep
) -> ConnectionCheckResponse:
    return to_connection_check_response(await diagnostics.check_connection(payload.model))


@router.get(
    "/pipeline-stats",
    response_model=PipelineStatsResponse,
    summary="Count what the pipeline holds",
    description="Messages, runs by status, extractions by disposition, memories, and entities.",
)
async def pipeline_stats(queries: ConsoleQueriesDep) -> PipelineStatsResponse:
    return to_pipeline_stats_response(await queries.pipeline_stats())
