from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import PrincipalDep, ScheduleServiceDep
from app.api.v1.app_mappers import to_activity_response
from app.core.exceptions import ErrorResponse
from app.schemas.app import ActivityItemResponse
from app.schemas.common import Page, PageParams

router = APIRouter()


@router.get(
    "",
    response_model=Page[ActivityItemResponse],
    responses={401: {"model": ErrorResponse, "description": "No valid access token"}},
    summary="List what the assistant did on its own",
    description="Finished scheduled runs, newest first, with their result and where it went.",
)
async def list_activity(
    principal: PrincipalDep,
    schedules: ScheduleServiceDep,
    page: Annotated[PageParams, Depends()],
) -> Page[ActivityItemResponse]:
    entries, total = await schedules.activity(principal, limit=page.limit, offset=page.offset)
    return Page(
        items=[to_activity_response(entry) for entry in entries],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
