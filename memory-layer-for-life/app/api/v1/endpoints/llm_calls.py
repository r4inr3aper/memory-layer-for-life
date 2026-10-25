import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import ConsoleQueriesDep
from app.api.v1.console_mappers import (
    to_llm_call_page,
    to_llm_call_response,
    to_usage_summary_response,
)
from app.core.exceptions import ErrorResponse
from app.repositories.llm_call_repository import LlmCallFilter
from app.schemas.common import Page, PageParams
from app.schemas.llm_call import LlmCallFilterParams, LlmCallResponse, UsageSummaryResponse

router = APIRouter()


def _selection(params: LlmCallFilterParams) -> LlmCallFilter:
    return LlmCallFilter(**params.model_dump())


@router.get(
    "",
    response_model=Page[LlmCallResponse],
    summary="List model calls",
    description=(
        "Newest first. Every call the application made to a model provider, with its "
        "tokens, estimated cost, timing, and outcome. Never the content of a call."
    ),
)
async def list_calls(
    queries: ConsoleQueriesDep,
    selection: Annotated[LlmCallFilterParams, Depends()],
    page: Annotated[PageParams, Depends()],
) -> Page[LlmCallResponse]:
    result = await queries.list_calls(_selection(selection), limit=page.limit, offset=page.offset)
    return to_llm_call_page(result, limit=page.limit, offset=page.offset)


@router.get(
    "/usage",
    response_model=UsageSummaryResponse,
    summary="Summarize usage and cost",
    description=(
        "Tokens, estimated cost, latency, and failures of the selected calls, in total "
        "and by model, origin, operation, and day. Cost is an estimate from list prices."
    ),
)
async def usage_summary(
    queries: ConsoleQueriesDep, selection: Annotated[LlmCallFilterParams, Depends()]
) -> UsageSummaryResponse:
    summary = await queries.usage_summary(_selection(selection))
    return to_usage_summary_response(summary, timezone_name=queries.timezone_name)


@router.get(
    "/{call_id}",
    response_model=LlmCallResponse,
    responses={404: {"model": ErrorResponse, "description": "No such call"}},
    summary="Inspect one model call",
)
async def get_call(call_id: uuid.UUID, queries: ConsoleQueriesDep) -> LlmCallResponse:
    return to_llm_call_response(await queries.get_call(call_id))
