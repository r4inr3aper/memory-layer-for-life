"""The signed-in user's saved links: addresses the assistant shares for them (ADR-050)."""

import uuid
from typing import Any

from fastapi import APIRouter, Response, status

from app.api.dependencies import LinkServiceDep, PrincipalDep
from app.core.exceptions import ErrorResponse
from app.schemas.links import LinkResponse, SavedLinkResponse, SaveLinkRequest, UpdateLinkRequest
from app.services.links import LinkView

router = APIRouter()

Responses = dict[int | str, dict[str, Any]]

_AUTH: Responses = {
    401: {"model": ErrorResponse, "description": "No valid access token"},
    503: {"model": ErrorResponse, "description": "User sign-in is not configured"},
}
_NOT_FOUND: Responses = {404: {"model": ErrorResponse, "description": "No such link"}}
_INVALID: Responses = {
    422: {"model": ErrorResponse, "description": "Not a web address, or already saved"}
}


def _response(view: LinkView) -> LinkResponse:
    return LinkResponse.model_validate(view)


@router.get(
    "",
    response_model=list[LinkResponse],
    responses=_AUTH,
    summary="List my saved links",
    description="The resume link first, then the most recently changed.",
)
async def list_links(principal: PrincipalDep, links: LinkServiceDep) -> list[LinkResponse]:
    return [_response(view) for view in await links.list_links(principal)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SavedLinkResponse,
    responses={**_AUTH, **_INVALID},
    summary="Save a link",
    description=(
        "Saves a web address for the assistant to share, such as a resume on Google Drive. "
        "The same address again updates the saved link. Nothing is fetched from it."
    ),
)
async def save_link(
    payload: SaveLinkRequest, principal: PrincipalDep, links: LinkServiceDep
) -> SavedLinkResponse:
    saved = await links.save(principal, url=payload.url, title=payload.title, kind=payload.kind)
    return SavedLinkResponse(**_response(saved.link).model_dump(), created=saved.created)


@router.patch(
    "/{link_id}",
    response_model=LinkResponse,
    responses={**_AUTH, **_NOT_FOUND, **_INVALID},
    summary="Change a saved link",
)
async def update_link(
    link_id: uuid.UUID,
    payload: UpdateLinkRequest,
    principal: PrincipalDep,
    links: LinkServiceDep,
) -> LinkResponse:
    return _response(
        await links.update(
            principal, link_id, url=payload.url, title=payload.title, kind=payload.kind
        )
    )


@router.delete(
    "/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_AUTH, **_NOT_FOUND},
    summary="Delete a saved link",
)
async def delete_link(
    link_id: uuid.UUID, principal: PrincipalDep, links: LinkServiceDep
) -> Response:
    await links.delete(principal, link_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
