import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import PrincipalDep, ScheduleServiceDep
from app.api.v1.app_mappers import to_run_response, to_schedule_response
from app.core.exceptions import ErrorResponse
from app.domain.schedule_rules import RuleFields, parse_local_time
from app.schemas.app import (
    CreateScheduleRequest,
    ScheduleResponse,
    ScheduleRunResponse,
    UpdateScheduleRequest,
)
from app.schemas.common import Page, PageParams
from app.services.schedules import NewSchedule, RuleChanges, ScheduleChanges

router = APIRouter()

# FastAPI's type for documented responses.
Responses = dict[int | str, dict[str, Any]]

_AUTH: Responses = {
    401: {"model": ErrorResponse, "description": "No valid access token"},
    503: {"model": ErrorResponse, "description": "User sign-in is not configured"},
}
_NOT_FOUND: Responses = {
    404: {"model": ErrorResponse, "description": "No such schedule for this user"}
}


@router.get(
    "",
    response_model=Page[ScheduleResponse],
    responses=_AUTH,
    summary="List schedules",
    description="Newest first, each with its number of runs and its latest result.",
)
async def list_schedules(
    principal: PrincipalDep,
    schedules: ScheduleServiceDep,
    page: Annotated[PageParams, Depends()],
) -> Page[ScheduleResponse]:
    items, total = await schedules.list_schedules(principal, limit=page.limit, offset=page.offset)
    return Page(
        items=[to_schedule_response(task, count) for task, count in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ScheduleResponse,
    responses={**_AUTH, 422: {"model": ErrorResponse, "description": "Not a valid schedule"}},
    summary="Create a schedule",
    description=(
        "For schedules the user writes themselves: once on a date, daily, weekly on chosen "
        "days, monthly on a day, or every few hours. Results delivered to chat go to the "
        "main thread; results can only go to an app the user has connected. A one-time "
        "schedule in the past is refused."
    ),
)
async def create_schedule(
    payload: CreateScheduleRequest, principal: PrincipalDep, schedules: ScheduleServiceDep
) -> ScheduleResponse:
    task, count = await schedules.create(
        principal,
        NewSchedule(
            title=payload.title,
            task=payload.task,
            rule=RuleFields(
                frequency=payload.frequency,
                local_time=parse_local_time(payload.local_time),
                timezone=payload.timezone,
                weekdays=tuple(payload.weekdays or ()),
                day_of_month=payload.day_of_month,
                start_date=payload.start_date,
                interval_hours=payload.interval_hours,
            ),
            delivery=payload.delivery,
            delivery_target=payload.delivery_target,
        ),
    )
    return to_schedule_response(task, count)


@router.get(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    responses={**_AUTH, **_NOT_FOUND},
    summary="Show one schedule",
)
async def get_schedule(
    schedule_id: uuid.UUID, principal: PrincipalDep, schedules: ScheduleServiceDep
) -> ScheduleResponse:
    task, count = await schedules.get(principal, schedule_id)
    return to_schedule_response(task, count)


@router.patch(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    responses={
        **_AUTH,
        **_NOT_FOUND,
        422: {"model": ErrorResponse, "description": "The change is not allowed"},
    },
    summary="Edit, pause, resume, or cancel a schedule",
    description=(
        "Only the fields sent change. A rule change needs only the fields that differ, and "
        "moves the next run to the new rule's first slot after now; editing a completed "
        "one-time schedule to a future time makes it active again. Resuming schedules the "
        "next slot from now; missed slots are skipped. Cancelling is final."
    ),
)
async def update_schedule(
    schedule_id: uuid.UUID,
    payload: UpdateScheduleRequest,
    principal: PrincipalDep,
    schedules: ScheduleServiceDep,
) -> ScheduleResponse:
    task, count = await schedules.update(principal, schedule_id, _changes(payload))
    return to_schedule_response(task, count)


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **_AUTH,
        **_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "The schedule is running"},
    },
    summary="Delete a schedule",
    description=(
        "Deletes the schedule and its run history. Results already posted stay in chat. "
        "Refused while a run is in progress."
    ),
)
async def delete_schedule(
    schedule_id: uuid.UUID, principal: PrincipalDep, schedules: ScheduleServiceDep
) -> Response:
    await schedules.delete(principal, schedule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _changes(payload: UpdateScheduleRequest) -> ScheduleChanges:
    sent = payload.model_fields_set
    rule = None
    if payload.changes_rule:
        rule = RuleChanges(
            frequency=payload.frequency,
            local_time=(
                parse_local_time(payload.local_time) if payload.local_time is not None else None
            ),
            timezone=payload.timezone,
            weekdays=tuple(payload.weekdays) if payload.weekdays is not None else None,
            day_of_month=payload.day_of_month,
            start_date=payload.start_date,
            interval_hours=payload.interval_hours,
        )
    return ScheduleChanges(
        title=payload.title,
        task=payload.task,
        rule=rule,
        delivery=payload.delivery,
        delivery_target=payload.delivery_target,
        delivery_target_given="delivery_target" in sent,
        status=payload.status,
    )


@router.post(
    "/{schedule_id}/runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ScheduleRunResponse,
    responses={
        **_AUTH,
        **_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "The schedule is already running"},
        422: {"model": ErrorResponse, "description": "The schedule is cancelled"},
    },
    summary="Run a schedule now",
    description=(
        "Starts a run in the background and returns it. Poll the run until its status is "
        "no longer `running`. The next scheduled slot is unchanged."
    ),
)
async def run_schedule(
    schedule_id: uuid.UUID, principal: PrincipalDep, schedules: ScheduleServiceDep
) -> ScheduleRunResponse:
    return to_run_response(await schedules.start_manual_run(principal, schedule_id))


@router.get(
    "/{schedule_id}/runs",
    response_model=Page[ScheduleRunResponse],
    responses={**_AUTH, **_NOT_FOUND},
    summary="List a schedule's runs",
    description="Newest first.",
)
async def list_runs(
    schedule_id: uuid.UUID,
    principal: PrincipalDep,
    schedules: ScheduleServiceDep,
    page: Annotated[PageParams, Depends()],
) -> Page[ScheduleRunResponse]:
    runs, total = await schedules.list_runs(
        principal, schedule_id, limit=page.limit, offset=page.offset
    )
    return Page(
        items=[to_run_response(run) for run in runs],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{schedule_id}/runs/{run_id}",
    response_model=ScheduleRunResponse,
    responses={
        **_AUTH,
        404: {"model": ErrorResponse, "description": "No such schedule or run"},
    },
    summary="Show one run",
)
async def get_run(
    schedule_id: uuid.UUID,
    run_id: uuid.UUID,
    principal: PrincipalDep,
    schedules: ScheduleServiceDep,
) -> ScheduleRunResponse:
    return to_run_response(await schedules.get_run(principal, schedule_id, run_id))
