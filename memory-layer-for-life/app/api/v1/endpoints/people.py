"""The people, places, and things in the signed-in user's memories."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.dependencies import PeopleServiceDep, PrincipalDep
from app.api.v1.memory_app_mappers import to_person_detail_response, to_person_response
from app.core.exceptions import ErrorResponse
from app.domain.enums import EntityType
from app.schemas.common import Page, PageParams
from app.schemas.my_memories import (
    MergePersonRequest,
    PersonDetailResponse,
    PersonResponse,
    RenamePersonRequest,
)

router = APIRouter()

Responses = dict[int | str, dict[str, Any]]

_AUTH: Responses = {
    401: {"model": ErrorResponse, "description": "No valid access token"},
    503: {"model": ErrorResponse, "description": "User sign-in is not configured"},
}
_MISSING: Responses = {404: {"model": ErrorResponse, "description": "No such person"}}
_INVALID: Responses = {422: {"model": ErrorResponse, "description": "Not a valid change"}}


@router.get(
    "",
    response_model=Page[PersonResponse],
    responses=_AUTH,
    summary="List the people and things in my memories",
    description=(
        "Those that current memories mention, most mentioned first. Filter by "
        "`entity_type`, for example `person` or `place`."
    ),
)
async def list_people(
    principal: PrincipalDep,
    people: PeopleServiceDep,
    page: Annotated[PageParams, Depends()],
    entity_type: EntityType | None = None,
) -> Page[PersonResponse]:
    result = await people.list_people(
        principal, entity_type=entity_type, limit=page.limit, offset=page.offset
    )
    return Page[PersonResponse](
        items=[to_person_response(person) for person in result.items],
        total=result.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{person_id}",
    response_model=PersonDetailResponse,
    responses={**_AUTH, **_MISSING},
    summary="Show a person with their memories",
    description="A person merged into another answers with the one they were merged into.",
)
async def get_person(
    person_id: uuid.UUID, principal: PrincipalDep, people: PeopleServiceDep
) -> PersonDetailResponse:
    return to_person_detail_response(await people.get(principal, person_id))


@router.patch(
    "/{person_id}",
    response_model=PersonDetailResponse,
    responses={**_AUTH, **_MISSING, **_INVALID},
    summary="Rename a person",
    description="The old name is kept as another name, so messages using it still match.",
)
async def rename_person(
    person_id: uuid.UUID,
    payload: RenamePersonRequest,
    principal: PrincipalDep,
    people: PeopleServiceDep,
) -> PersonDetailResponse:
    return to_person_detail_response(await people.rename(principal, person_id, payload.name))


@router.post(
    "/{person_id}/merge",
    response_model=PersonDetailResponse,
    responses={**_AUTH, **_MISSING, **_INVALID},
    summary="Merge two people who are one",
    description=(
        "The other person's memories and mentions move to this one, and their name "
        "becomes another name of this one."
    ),
)
async def merge_person(
    person_id: uuid.UUID,
    payload: MergePersonRequest,
    principal: PrincipalDep,
    people: PeopleServiceDep,
) -> PersonDetailResponse:
    return to_person_detail_response(
        await people.merge(principal, person_id, payload.other_person_id)
    )
