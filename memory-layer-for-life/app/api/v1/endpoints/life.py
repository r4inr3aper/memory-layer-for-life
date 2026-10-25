"""The signed-in user's life state, today's brief, and searching their chats."""

from typing import Any

from fastapi import APIRouter

from app.api.dependencies import ChatServiceDep, LifeStateServiceDep, PrincipalDep
from app.api.v1.mappers import to_memory_response
from app.core.exceptions import ErrorResponse
from app.domain.enums import LifeBucket
from app.schemas.life import (
    BriefItemResponse,
    BriefResponse,
    LifeOverviewResponse,
    MessageHitResponse,
    MessageSearchRequest,
    MessageSearchResponse,
)

router = APIRouter()

Responses = dict[int | str, dict[str, Any]]

_AUTH: Responses = {
    401: {"model": ErrorResponse, "description": "No valid access token"},
    503: {"model": ErrorResponse, "description": "User sign-in is not configured"},
}


@router.get(
    "/life",
    response_model=LifeOverviewResponse,
    responses=_AUTH,
    summary="Show what is open in my life",
    description=(
        "Open tasks, plans, commitments, open loops, and intentions by when they are due "
        "(in the user's timezone), goals and projects, items gone quiet, pending reminders, "
        "and what was done in the last seven days."
    ),
)
async def get_life(principal: PrincipalDep, life: LifeStateServiceDep) -> LifeOverviewResponse:
    overview = await life.overview(principal)

    def items(bucket: LifeBucket) -> list[Any]:
        return [to_memory_response(view) for view in overview.buckets[bucket]]

    return LifeOverviewResponse(
        today=overview.today,
        timezone=overview.timezone,
        overdue=items(LifeBucket.OVERDUE),
        due_today=items(LifeBucket.TODAY),
        upcoming=items(LifeBucket.UPCOMING),
        later=items(LifeBucket.LATER),
        someday=items(LifeBucket.SOMEDAY),
        goals=[to_memory_response(view) for view in overview.goals],
        stale_ids=sorted(overview.stale_ids, key=str),
        reminders=[to_memory_response(view) for view in overview.reminders],
        recently_done=[to_memory_response(view) for view in overview.recently_done],
    )


@router.get(
    "/life/brief",
    response_model=BriefResponse,
    responses=_AUTH,
    summary="Preview today's brief",
    description="The daily brief as it stands now, without sending it. Never sensitive items.",
)
async def get_brief(principal: PrincipalDep, life: LifeStateServiceDep) -> BriefResponse:
    brief = await life.brief(principal)
    return BriefResponse(
        text=brief.text,
        summary=brief.summary,
        follow_ups=[
            BriefItemResponse(memory_id=item.memory_id, content=item.content, due_on=item.due_on)
            for item in brief.follow_ups
        ],
        nothing_to_say=brief.nothing_to_say,
    )


@router.post(
    "/messages/search",
    response_model=MessageSearchResponse,
    responses={**_AUTH, 422: {"model": ErrorResponse, "description": "Not a valid search"}},
    summary="Search my chats",
    description=(
        "The user's chat messages, theirs and the assistant's, containing the query's words "
        "(stemmed English and exact words), best first, each with its thread and a snippet."
    ),
)
async def search_messages(
    payload: MessageSearchRequest, principal: PrincipalDep, chat: ChatServiceDep
) -> MessageSearchResponse:
    hits = await chat.search_messages(principal, payload.query, limit=payload.limit)
    return MessageSearchResponse(
        query=payload.query,
        items=[MessageHitResponse.model_validate(hit) for hit in hits],
    )
