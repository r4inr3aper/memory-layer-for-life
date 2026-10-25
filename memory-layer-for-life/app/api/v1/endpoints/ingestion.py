from fastapi import APIRouter, BackgroundTasks, status

from app.api.dependencies import IngestionServiceDep, PipelineRunnerDep
from app.api.v1.mappers import to_ingest_unit_response
from app.core.exceptions import ErrorResponse
from app.schemas.ingestion import (
    IngestBatchRequest,
    IngestBatchResponse,
    IngestUnitRequest,
    IngestUnitResponse,
)

router = APIRouter()

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    409: {"model": ErrorResponse, "description": "A source id was redelivered with new content"},
    422: {"model": ErrorResponse, "description": "The request is not valid"},
}


@router.post(
    "/units",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestUnitResponse,
    responses=_ERROR_RESPONSES,
    summary="Capture one processing unit",
    description=(
        "Stores the messages of one unit and queues it for processing. The messages are "
        "committed before the response is sent, and processing happens afterwards, so a "
        "processing failure can never lose input. Redelivering a message with the same "
        "source id and content is safe and creates nothing new."
    ),
)
async def ingest_unit(
    payload: IngestUnitRequest,
    background_tasks: BackgroundTasks,
    ingestion: IngestionServiceDep,
    runner: PipelineRunnerDep,
) -> IngestUnitResponse:
    (unit,) = await ingestion.ingest([payload.messages])
    if runner.can_process:
        background_tasks.add_task(runner.process_runs, [unit.run.id])
    return to_ingest_unit_response(unit)


@router.post(
    "/batches",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestBatchResponse,
    responses=_ERROR_RESPONSES,
    summary="Capture several processing units",
    description=(
        "Stores all units in one transaction: either every unit is accepted or none is. "
        "Units are then processed one after another in the background."
    ),
)
async def ingest_batch(
    payload: IngestBatchRequest,
    background_tasks: BackgroundTasks,
    ingestion: IngestionServiceDep,
    runner: PipelineRunnerDep,
) -> IngestBatchResponse:
    units = await ingestion.ingest([unit.messages for unit in payload.units])
    if runner.can_process:
        background_tasks.add_task(runner.process_runs, [unit.run.id for unit in units])
    return IngestBatchResponse(units=[to_ingest_unit_response(unit) for unit in units])
