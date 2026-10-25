import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import MemoryQueriesDep, RetrievalEngineDep
from app.api.v1.mappers import to_memory_detail_response, to_memory_page
from app.api.v1.retrieval_mappers import to_memory_search_response, to_retrieval_query
from app.core.exceptions import ErrorResponse
from app.domain.enums import LlmCallOrigin, MemoryStatus, MemoryType
from app.integrations.llm_calls import LlmCallContext
from app.schemas.common import Page, PageParams
from app.schemas.memory import MemoryDetailResponse, MemoryResponse
from app.schemas.retrieval import MemorySearchRequest, MemorySearchResponse

router = APIRouter()


@router.get(
    "",
    response_model=Page[MemoryResponse],
    summary="List memories",
    description="Newest first. Pipeline output is `proposed` until it is reviewed.",
)
async def list_memories(
    queries: MemoryQueriesDep,
    page: Annotated[PageParams, Depends()],
    memory_status: Annotated[MemoryStatus | None, Query(alias="status")] = None,
    memory_type: MemoryType | None = None,
    processing_run_id: Annotated[
        uuid.UUID | None, Query(description="Only memories produced by this run.")
    ] = None,
) -> Page[MemoryResponse]:
    result = await queries.list_memories(
        status=memory_status,
        memory_type=memory_type,
        processing_run_id=processing_run_id,
        limit=page.limit,
        offset=page.offset,
    )
    return to_memory_page(result, limit=page.limit, offset=page.offset)


@router.post(
    "/search",
    response_model=MemorySearchResponse,
    responses={422: {"model": ErrorResponse, "description": "Not a valid search"}},
    summary="Search memories",
    description=(
        "The operator's own memories only; app users search theirs through "
        "`/me/memories/search`. Words, names, and meaning, each result with its evidence."
    ),
)
async def search_memories(
    payload: MemorySearchRequest, engine: RetrievalEngineDep
) -> MemorySearchResponse:
    result = await engine.search(
        to_retrieval_query(payload, None),
        context=LlmCallContext(origin=LlmCallOrigin.RETRIEVAL),
    )
    return to_memory_search_response(result)


@router.get(
    "/{memory_id}",
    response_model=MemoryDetailResponse,
    responses={404: {"model": ErrorResponse, "description": "No such memory"}},
    summary="Inspect one memory with its evidence",
    description=(
        "The memory, every source message it rests on with the quoted evidence, the run "
        "that produced it, and the entities it involves."
    ),
)
async def get_memory(memory_id: uuid.UUID, queries: MemoryQueriesDep) -> MemoryDetailResponse:
    return to_memory_detail_response(await queries.get_memory(memory_id))
