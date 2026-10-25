import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from app.api.dependencies import PipelineRunnerDep, ProcessingQueriesDep, ReplayServiceDep
from app.api.v1.mappers import (
    to_replay_outcome_response,
    to_run_detail_response,
    to_run_page,
)
from app.core.exceptions import ErrorResponse
from app.domain.enums import ProcessingStatus, ReplayAction
from app.schemas.common import Page, PageParams
from app.schemas.processing import (
    ProcessingRunDetailResponse,
    ProcessingRunResponse,
    ReplayRequest,
    ReplayResponse,
)

router = APIRouter()


@router.get(
    "/runs",
    response_model=Page[ProcessingRunResponse],
    summary="List processing runs",
    description="Newest first. Filter by status to inspect failures or runs awaiting review.",
)
async def list_runs(
    queries: ProcessingQueriesDep,
    page: Annotated[PageParams, Depends()],
    run_status: Annotated[ProcessingStatus | None, Query(alias="status")] = None,
    raw_message_id: Annotated[
        uuid.UUID | None, Query(description="Only runs whose unit contains this message.")
    ] = None,
) -> Page[ProcessingRunResponse]:
    result = await queries.list_runs(
        status=run_status, raw_message_id=raw_message_id, limit=page.limit, offset=page.offset
    )
    return to_run_page(result, limit=page.limit, offset=page.offset)


@router.get(
    "/runs/{run_id}",
    response_model=ProcessingRunDetailResponse,
    responses={404: {"model": ErrorResponse, "description": "No such run"}},
    summary="Inspect one processing run",
    description="The run, the audit log of every attempt, and the memories it produced.",
)
async def get_run(run_id: uuid.UUID, queries: ProcessingQueriesDep) -> ProcessingRunDetailResponse:
    return to_run_detail_response(await queries.get_run(run_id))


@router.post(
    "/replays",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReplayResponse,
    responses={422: {"model": ErrorResponse, "description": "The request is not valid"}},
    summary="Reprocess stored units",
    description=(
        "Ensures each selected unit has a run for the current pipeline configuration. "
        "Units processed under an older configuration get a new run and keep their "
        "history. Failed runs are queued again. Succeeded runs are left alone, so "
        "replaying an unchanged configuration has no effect. Replay never creates a raw "
        "message, and it only selects the operator's own units, never app users'."
    ),
)
async def replay(
    payload: ReplayRequest,
    background_tasks: BackgroundTasks,
    replays: ReplayServiceDep,
    runner: PipelineRunnerDep,
) -> ReplayResponse:
    outcomes = await replays.replay(
        raw_message_ids=payload.raw_message_ids, run_ids=payload.run_ids, limit=payload.limit
    )
    to_process = [
        outcome.run.id for outcome in outcomes if outcome.action is not ReplayAction.UNCHANGED
    ]
    if to_process and runner.can_process:
        background_tasks.add_task(runner.process_runs, to_process)
    return ReplayResponse(outcomes=[to_replay_outcome_response(outcome) for outcome in outcomes])
