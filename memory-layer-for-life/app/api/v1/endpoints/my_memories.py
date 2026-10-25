"""The signed-in user's memories: list, search, read with evidence and history, write,
review, correct, merge, and delete."""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import (
    LifeStateServiceDep,
    MemoryReviewServiceDep,
    MemoryServiceDep,
    PrincipalDep,
    RetrievalEngineDep,
)
from app.api.v1.mappers import to_memory_page, to_memory_response
from app.api.v1.memory_app_mappers import to_my_memory_detail_response, to_review_inbox_response
from app.api.v1.retrieval_mappers import to_memory_search_response, to_retrieval_query
from app.core.exceptions import ErrorResponse
from app.domain.enums import LlmCallOrigin, MemoryStatus, MemoryType
from app.domain.memory_review import LIVE_STATUSES
from app.integrations.llm_calls import LlmCallContext
from app.schemas.common import Page, PageParams
from app.schemas.memory import MemoryResponse
from app.schemas.my_memories import (
    AcceptMemoriesRequest,
    AcceptMemoriesResponse,
    CreateMemoryRequest,
    DeleteMemoryResponse,
    DismissSuggestionRequest,
    MyMemoryDetailResponse,
    OtherMemoryRequest,
    ReviewInboxResponse,
    UpdateMemoryRequest,
)
from app.schemas.retrieval import MemorySearchRequest, MemorySearchResponse
from app.services.memories import MemoryChanges, NewMemory

router = APIRouter()

Responses = dict[int | str, dict[str, Any]]

_AUTH: Responses = {
    401: {"model": ErrorResponse, "description": "No valid access token"},
    503: {"model": ErrorResponse, "description": "User sign-in is not configured"},
}
_MISSING: Responses = {404: {"model": ErrorResponse, "description": "No such memory"}}
_INVALID: Responses = {422: {"model": ErrorResponse, "description": "Not a valid change"}}
_STATE: Responses = {
    409: {
        "model": ErrorResponse,
        "description": "The memory was replaced by a newer one, or marked as wrong",
    }
}


@router.get(
    "",
    response_model=Page[MemoryResponse],
    responses=_AUTH,
    summary="List my memories",
    description=(
        "Newest first unless `order=oldest`. Without `status`, the memories that may still "
        "be true: `proposed` (saved from chat, not yet reviewed) and `active`. Repeat "
        "`status` for several."
    ),
)
async def list_my_memories(
    principal: PrincipalDep,
    memories: MemoryServiceDep,
    page: Annotated[PageParams, Depends()],
    memory_status: Annotated[list[MemoryStatus] | None, Query(alias="status")] = None,
    memory_type: MemoryType | None = None,
    order: Literal["newest", "oldest"] = "newest",
) -> Page[MemoryResponse]:
    result = await memories.list_memories(
        principal,
        statuses=frozenset(memory_status) if memory_status else LIVE_STATUSES,
        memory_type=memory_type,
        oldest_first=order == "oldest",
        limit=page.limit,
        offset=page.offset,
    )
    return to_memory_page(result, limit=page.limit, offset=page.offset)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=MemoryResponse,
    responses={**_AUTH, **_INVALID},
    summary="Write a memory",
    description="Saved as `active`, written by the user.",
)
async def create_memory(
    payload: CreateMemoryRequest, principal: PrincipalDep, memories: MemoryServiceDep
) -> MemoryResponse:
    created = await memories.create(
        principal,
        NewMemory(
            memory_type=payload.memory_type,
            content=payload.content,
            sensitive=payload.sensitive,
            due_on=payload.due_on,
            remind_at=payload.remind_at,
        ),
    )
    return to_memory_response(created)


@router.post(
    "/search",
    response_model=MemorySearchResponse,
    responses={**_AUTH, 422: {"model": ErrorResponse, "description": "Not a valid search"}},
    summary="Search my memories",
    description=(
        "Finds memories by their words, the people, places, and things they name, and "
        "their meaning (when embeddings are configured), and returns each with the "
        "messages it rests on. Memories with the same text appear once. Sensitive memories "
        "are included and marked. Without embeddings, or when the provider fails, the "
        "search still runs and says so in `degraded`."
    ),
)
async def search_my_memories(
    payload: MemorySearchRequest, principal: PrincipalDep, engine: RetrievalEngineDep
) -> MemorySearchResponse:
    result = await engine.search(
        to_retrieval_query(payload, principal.id),
        context=LlmCallContext(origin=LlmCallOrigin.RETRIEVAL, user_id=principal.id),
    )
    return to_memory_search_response(result)


# --- Review ------------------------------------------------------------------------------


@router.get(
    "/review",
    response_model=ReviewInboxResponse,
    responses=_AUTH,
    summary="Show what needs review",
    description=(
        "How many memories wait to be accepted (list them with `status=proposed`), pairs "
        "that look like duplicates or conflicts, and messages held back from becoming "
        "memories. Suggestions are found without any model."
    ),
)
async def get_review_inbox(
    principal: PrincipalDep, review: MemoryReviewServiceDep
) -> ReviewInboxResponse:
    return to_review_inbox_response(await review.inbox(principal))


@router.post(
    "/review/accept",
    response_model=AcceptMemoriesResponse,
    responses={**_AUTH, **_INVALID},
    summary="Accept several memories",
    description="Ids that are not proposed memories of the user are skipped.",
)
async def accept_memories(
    payload: AcceptMemoriesRequest, principal: PrincipalDep, memories: MemoryServiceDep
) -> AcceptMemoriesResponse:
    accepted = await memories.accept_many(principal, payload.memory_ids)
    return AcceptMemoriesResponse(accepted=accepted)


@router.post(
    "/review/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_AUTH, **_MISSING, **_INVALID},
    summary="Stop suggesting a pair",
    description="The two memories are not suggested together again.",
)
async def dismiss_suggestion(
    payload: DismissSuggestionRequest, principal: PrincipalDep, memories: MemoryServiceDep
) -> Response:
    await memories.dismiss_suggestion(
        principal, payload.first_memory_id, payload.second_memory_id, payload.kind.value
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/held-back/{run_id}/save",
    status_code=status.HTTP_201_CREATED,
    response_model=MemoryResponse,
    responses={
        **_AUTH,
        **_INVALID,
        404: {"model": ErrorResponse, "description": "No such held-back message"},
    },
    summary="Save a memory from a held-back message",
    description="The memory, written by the user, rests on the held-back message.",
)
async def save_held_back(
    run_id: uuid.UUID,
    payload: CreateMemoryRequest,
    principal: PrincipalDep,
    review: MemoryReviewServiceDep,
) -> MemoryResponse:
    created = await review.save_held_back(
        principal,
        run_id,
        NewMemory(
            memory_type=payload.memory_type,
            content=payload.content,
            sensitive=payload.sensitive,
            due_on=payload.due_on,
            remind_at=payload.remind_at,
        ),
    )
    return to_memory_response(created)


@router.post(
    "/held-back/{run_id}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_AUTH, 404: {"model": ErrorResponse, "description": "No such held-back message"}},
    summary="Dismiss a held-back message",
)
async def dismiss_held_back(
    run_id: uuid.UUID, principal: PrincipalDep, review: MemoryReviewServiceDep
) -> Response:
    await review.dismiss_held_back(principal, run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/failed/{run_id}/retry",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_AUTH, 404: {"model": ErrorResponse, "description": "No such failed run"}},
    summary="Retry a failed memory save",
    description=(
        "Queues the run again so the pipeline can retry extraction from the same source "
        "messages."
    ),
)
async def retry_failed_run(
    run_id: uuid.UUID, principal: PrincipalDep, review: MemoryReviewServiceDep
) -> Response:
    await review.retry_failed(principal, run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- One memory --------------------------------------------------------------------------


@router.get(
    "/{memory_id}",
    response_model=MyMemoryDetailResponse,
    responses={**_AUTH, **_MISSING},
    summary="Show a memory with its evidence and history",
)
async def get_my_memory(
    memory_id: uuid.UUID, principal: PrincipalDep, memories: MemoryServiceDep
) -> MyMemoryDetailResponse:
    return to_my_memory_detail_response(await memories.get(principal, memory_id))


@router.patch(
    "/{memory_id}",
    response_model=MemoryResponse,
    responses={**_AUTH, **_MISSING, **_INVALID, **_STATE},
    summary="Edit or correct a memory",
    description=(
        "Kind and sensitivity change in place. New text makes a new `active` version, "
        "written by the user, that supersedes this one: the response is the new version, "
        "with its own id."
    ),
)
async def update_my_memory(
    memory_id: uuid.UUID,
    payload: UpdateMemoryRequest,
    principal: PrincipalDep,
    memories: MemoryServiceDep,
) -> MemoryResponse:
    sent = payload.model_fields_set
    changed = await memories.change(
        principal,
        memory_id,
        MemoryChanges(
            content=payload.content,
            memory_type=payload.memory_type,
            sensitive=payload.sensitive,
            due_on=payload.due_on,
            due_on_given="due_on" in sent,
            remind_at=payload.remind_at,
            remind_at_given="remind_at" in sent,
        ),
    )
    return to_memory_response(changed)


@router.post(
    "/{memory_id}/complete",
    response_model=MemoryResponse,
    responses={**_AUTH, **_MISSING, **_STATE},
    summary="Mark an item done",
    description="Closes it as done, clears its reminder, and accepts it if it was proposed.",
)
async def complete_memory(
    memory_id: uuid.UUID, principal: PrincipalDep, life: LifeStateServiceDep
) -> MemoryResponse:
    return to_memory_response(await life.complete(principal, memory_id))


@router.post(
    "/{memory_id}/drop",
    response_model=MemoryResponse,
    responses={**_AUTH, **_MISSING, **_STATE},
    summary="Stop tracking an item",
    description="Closes it as dropped: no longer planned, though not done.",
)
async def drop_memory(
    memory_id: uuid.UUID, principal: PrincipalDep, life: LifeStateServiceDep
) -> MemoryResponse:
    return to_memory_response(await life.drop(principal, memory_id))


@router.post(
    "/{memory_id}/reopen",
    response_model=MemoryResponse,
    responses={**_AUTH, **_MISSING, **_STATE},
    summary="Open a closed item again",
)
async def reopen_memory(
    memory_id: uuid.UUID, principal: PrincipalDep, life: LifeStateServiceDep
) -> MemoryResponse:
    return to_memory_response(await life.reopen(principal, memory_id))


@router.delete(
    "/{memory_id}",
    response_model=DeleteMemoryResponse,
    responses={**_AUTH, **_MISSING},
    summary="Delete a memory",
    description=(
        "Deletes the memory with what it replaced (older versions, merged duplicates), "
        "their history, and their search index. The messages they came from stay in chat. "
        "Cannot be undone."
    ),
)
async def delete_my_memory(
    memory_id: uuid.UUID, principal: PrincipalDep, memories: MemoryServiceDep
) -> DeleteMemoryResponse:
    return DeleteMemoryResponse(deleted=await memories.delete(principal, memory_id))


@router.post(
    "/{memory_id}/accept",
    response_model=MemoryResponse,
    responses={**_AUTH, **_MISSING, **_STATE},
    summary="Accept a memory",
    description="A proposed memory becomes `active`. Accepting an active one changes nothing.",
)
async def accept_memory(
    memory_id: uuid.UUID, principal: PrincipalDep, memories: MemoryServiceDep
) -> MemoryResponse:
    return to_memory_response(await memories.accept(principal, memory_id))


@router.post(
    "/{memory_id}/retract",
    response_model=MemoryResponse,
    responses={**_AUTH, **_MISSING, **_STATE},
    summary="Mark a memory as wrong",
    description="It is kept in the history, never used again, and can be restored.",
)
async def retract_memory(
    memory_id: uuid.UUID, principal: PrincipalDep, memories: MemoryServiceDep
) -> MemoryResponse:
    return to_memory_response(await memories.retract(principal, memory_id))


@router.post(
    "/{memory_id}/restore",
    response_model=MemoryResponse,
    responses={**_AUTH, **_MISSING, **_STATE},
    summary="Restore a memory marked as wrong",
    description="It comes back as `active`.",
)
async def restore_memory(
    memory_id: uuid.UUID, principal: PrincipalDep, memories: MemoryServiceDep
) -> MemoryResponse:
    return to_memory_response(await memories.restore(principal, memory_id))


@router.post(
    "/{memory_id}/merge",
    response_model=MemoryResponse,
    responses={**_AUTH, **_MISSING, **_INVALID, **_STATE},
    summary="Merge a duplicate into this memory",
    description=(
        "This memory takes the other's evidence and people and becomes `active`; the "
        "other becomes `superseded`."
    ),
)
async def merge_memory(
    memory_id: uuid.UUID,
    payload: OtherMemoryRequest,
    principal: PrincipalDep,
    memories: MemoryServiceDep,
) -> MemoryResponse:
    return to_memory_response(await memories.merge(principal, memory_id, payload.other_memory_id))


@router.post(
    "/{memory_id}/replace",
    response_model=MemoryResponse,
    responses={**_AUTH, **_MISSING, **_INVALID, **_STATE},
    summary="Keep this memory over an out-of-date one",
    description="This memory becomes `active`; the other becomes `superseded`.",
)
async def replace_memory(
    memory_id: uuid.UUID,
    payload: OtherMemoryRequest,
    principal: PrincipalDep,
    memories: MemoryServiceDep,
) -> MemoryResponse:
    return to_memory_response(await memories.replace(principal, memory_id, payload.other_memory_id))
