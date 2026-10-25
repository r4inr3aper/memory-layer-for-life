import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import ConsoleQueriesDep, EvaluationServiceDep
from app.api.v1.console_mappers import (
    to_case_failure_responses,
    to_dataset_response,
    to_evaluation_case_detail_response,
    to_evaluation_case_page,
    to_evaluation_run_page,
    to_evaluation_run_response,
)
from app.core.exceptions import ErrorResponse
from app.domain.enums import EvaluationCaseOutcome, EvaluationRunStatus
from app.schemas.common import Page, PageParams
from app.schemas.evaluation import (
    CaseFailureResponse,
    DatasetResponse,
    EvaluationCaseDetailResponse,
    EvaluationCaseSummaryResponse,
    EvaluationRunResponse,
    EvaluationStartRequest,
)
from app.services.evaluations import EvaluationOptions

router = APIRouter()

_NOT_FOUND: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "No such evaluation run"}
}


@router.get(
    "",
    response_model=Page[EvaluationRunResponse],
    summary="List evaluation runs",
    description="Newest first. A run still marked running is updated as its cases finish.",
)
async def list_runs(
    queries: ConsoleQueriesDep,
    evaluations: EvaluationServiceDep,
    page: Annotated[PageParams, Depends()],
    run_status: Annotated[EvaluationRunStatus | None, Query(alias="status")] = None,
    extractor_model: str | None = None,
) -> Page[EvaluationRunResponse]:
    await evaluations.reap_stale()
    result = await queries.list_evaluation_runs(
        status=run_status, extractor_model=extractor_model, limit=page.limit, offset=page.offset
    )
    return to_evaluation_run_page(result, limit=page.limit, offset=page.offset)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=EvaluationRunResponse,
    responses={
        409: {
            "model": ErrorResponse,
            "description": "An evaluation is already running, or the dataset is unavailable",
        },
        422: {"model": ErrorResponse, "description": "The request is not valid"},
        503: {"model": ErrorResponse, "description": "No model provider is configured"},
    },
    summary="Start an evaluation",
    description=(
        "Runs the golden dataset, or the chosen cases, through a model in the background "
        "and scores every answer. This calls the model twice per case, so it costs money "
        "and sends the dataset's messages to the provider. One evaluation runs at a time."
    ),
)
async def start_run(
    payload: EvaluationStartRequest,
    evaluations: EvaluationServiceDep,
    queries: ConsoleQueriesDep,
) -> EvaluationRunResponse:
    run_id = await evaluations.start(
        EvaluationOptions(
            extractor_model=payload.extractor_model,
            extraction_effort=payload.extraction_effort,
            judge_model=payload.judge_model,
            judge_effort=payload.judge_effort,
            case_ids=tuple(payload.case_ids) if payload.case_ids is not None else None,
            concurrency=payload.concurrency,
        )
    )
    return to_evaluation_run_response(await queries.get_evaluation_run(run_id))


@router.get(
    "/dataset",
    response_model=DatasetResponse,
    summary="Describe the golden dataset",
    description="The cases that an evaluation can run, with a preview of each.",
)
async def get_dataset(evaluations: EvaluationServiceDep) -> DatasetResponse:
    return to_dataset_response(evaluations.dataset_info())


@router.get(
    "/failing-cases",
    response_model=list[CaseFailureResponse],
    summary="Cases that fail most often",
    description=(
        "Across completed runs. A case that fails every time points at the case or its "
        "label; one that fails now and then points at the model or the judge."
    ),
)
async def failing_cases(
    queries: ConsoleQueriesDep,
    extractor_model: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[CaseFailureResponse]:
    return to_case_failure_responses(
        await queries.failing_cases(extractor_model=extractor_model, limit=limit)
    )


@router.get(
    "/{run_id}",
    response_model=EvaluationRunResponse,
    responses=_NOT_FOUND,
    summary="Inspect one evaluation run",
)
async def get_run(run_id: uuid.UUID, queries: ConsoleQueriesDep) -> EvaluationRunResponse:
    return to_evaluation_run_response(await queries.get_evaluation_run(run_id))


@router.get(
    "/{run_id}/cases",
    response_model=Page[EvaluationCaseSummaryResponse],
    responses=_NOT_FOUND,
    summary="List the cases of a run",
    description="In dataset order. Filter by outcome to see only the failures.",
)
async def list_cases(
    run_id: uuid.UUID,
    queries: ConsoleQueriesDep,
    page: Annotated[PageParams, Depends()],
    outcome: EvaluationCaseOutcome | None = None,
) -> Page[EvaluationCaseSummaryResponse]:
    result = await queries.list_evaluation_cases(
        run_id, outcome=outcome, limit=page.limit, offset=page.offset
    )
    return to_evaluation_case_page(result, limit=page.limit, offset=page.offset)


@router.get(
    "/{run_id}/cases/{case_id}",
    response_model=EvaluationCaseDetailResponse,
    responses={404: {"model": ErrorResponse, "description": "No such case in this run"}},
    summary="Inspect one case of a run",
    description=(
        "The source messages, the expected memory, what the model produced, every check, "
        "and the judge's explanations."
    ),
)
async def get_case(
    run_id: uuid.UUID, case_id: str, queries: ConsoleQueriesDep
) -> EvaluationCaseDetailResponse:
    return to_evaluation_case_detail_response(await queries.get_evaluation_case(run_id, case_id))


@router.post(
    "/{run_id}/cancel",
    response_model=EvaluationRunResponse,
    responses={
        404: _NOT_FOUND[404],
        409: {"model": ErrorResponse, "description": "This process is not running that run"},
    },
    summary="Cancel a running evaluation",
    description="Stops the run. Cases already scored are kept.",
)
async def cancel_run(
    run_id: uuid.UUID, evaluations: EvaluationServiceDep, queries: ConsoleQueriesDep
) -> EvaluationRunResponse:
    await queries.get_evaluation_run(run_id)
    await evaluations.cancel(run_id)
    return to_evaluation_run_response(await queries.get_evaluation_run(run_id))
