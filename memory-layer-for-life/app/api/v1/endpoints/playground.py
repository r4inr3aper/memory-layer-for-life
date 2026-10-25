import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies import ConsoleQueriesDep, PlaygroundServiceDep
from app.api.v1.console_mappers import (
    extraction_contract_response,
    to_playground_page,
    to_playground_run_response,
)
from app.core.exceptions import ErrorResponse
from app.schemas.common import Page, PageParams
from app.schemas.playground import (
    ExtractionContractResponse,
    PlaygroundRunRequest,
    PlaygroundRunResponse,
    PlaygroundRunSummaryResponse,
)
from app.services.playground import PlaygroundMessage

router = APIRouter()


@router.post(
    "/extractions",
    status_code=status.HTTP_201_CREATED,
    response_model=PlaygroundRunResponse,
    responses={
        422: {"model": ErrorResponse, "description": "The request is not valid"},
        503: {"model": ErrorResponse, "description": "No model provider is configured"},
    },
    summary="Make one test extraction",
    description=(
        "Sends the messages to the model as one unit and returns what came back, after "
        "the same checks the pipeline applies. Nothing is stored as a raw message, an "
        "entity, or a memory. The test and the model call are logged. A call the model "
        "fails is reported in the response, not as an error."
    ),
)
async def run_extraction(
    payload: PlaygroundRunRequest, playground: PlaygroundServiceDep
) -> PlaygroundRunResponse:
    result = await playground.run(
        [
            PlaygroundMessage(text=message.text, sent_at=message.sent_at)
            for message in payload.messages
        ],
        model=payload.model,
        effort=payload.effort,
        timezone_name=payload.timezone,
    )
    return to_playground_run_response(result)


@router.get(
    "/extractions",
    response_model=Page[PlaygroundRunSummaryResponse],
    summary="List test extractions",
    description="Newest first.",
)
async def list_extractions(
    queries: ConsoleQueriesDep, page: Annotated[PageParams, Depends()]
) -> Page[PlaygroundRunSummaryResponse]:
    result = await queries.list_playground_runs(limit=page.limit, offset=page.offset)
    return to_playground_page(result, limit=page.limit, offset=page.offset)


@router.get(
    "/extractions/{run_id}",
    response_model=PlaygroundRunResponse,
    responses={404: {"model": ErrorResponse, "description": "No such test"}},
    summary="Reopen one test extraction",
)
async def get_extraction(
    run_id: uuid.UUID, playground: PlaygroundServiceDep
) -> PlaygroundRunResponse:
    return to_playground_run_response(await playground.get(run_id))


@router.get(
    "/contract",
    response_model=ExtractionContractResponse,
    summary="Show the extraction output format",
    description="The JSON Schema an extraction must satisfy, and the one the provider is given.",
)
async def get_contract() -> ExtractionContractResponse:
    return extraction_contract_response()
