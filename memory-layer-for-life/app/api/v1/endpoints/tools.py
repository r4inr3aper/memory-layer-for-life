from typing import Any

from fastapi import APIRouter

from app.api.dependencies import PrincipalDep, ToolConnectionServiceDep
from app.api.v1.app_mappers import to_tool_response
from app.core.exceptions import ErrorResponse
from app.schemas.app import ConnectToolRequest, ConnectToolResponse, ToolResponse

router = APIRouter()

# FastAPI's type for documented responses.
Responses = dict[int | str, dict[str, Any]]

_AUTH: Responses = {401: {"model": ErrorResponse, "description": "No valid access token"}}
_COMPOSIO: Responses = {
    404: {"model": ErrorResponse, "description": "No such app in the catalog"},
    502: {"model": ErrorResponse, "description": "Composio failed"},
    503: {"model": ErrorResponse, "description": "Composio or sign-in is not configured"},
}


@router.get(
    "",
    response_model=list[ToolResponse],
    responses={
        **_AUTH,
        503: {"model": ErrorResponse, "description": "User sign-in is not configured"},
    },
    summary="List connectable apps",
    description="The whole catalog, each with the user's last known connection status.",
)
async def list_tools(
    principal: PrincipalDep, connections: ToolConnectionServiceDep
) -> list[ToolResponse]:
    return [to_tool_response(view) for view in await connections.list_tools(principal)]


@router.post(
    "/{slug}/connect",
    response_model=ConnectToolResponse,
    responses={**_AUTH, **_COMPOSIO},
    summary="Start connecting an app",
    description=(
        "Returns the address where the user authorizes the app. When the app is already "
        "connected, nothing is started and `connect_url` is absent."
    ),
)
async def connect_tool(
    slug: str,
    payload: ConnectToolRequest,
    principal: PrincipalDep,
    connections: ToolConnectionServiceDep,
) -> ConnectToolResponse:
    started = await connections.start_connection(principal, slug, callback_url=payload.callback_url)
    return ConnectToolResponse(tool=to_tool_response(started.view), connect_url=started.connect_url)


@router.get(
    "/{slug}/connection",
    response_model=ToolResponse,
    responses={**_AUTH, **_COMPOSIO},
    summary="Check an app connection",
    description="Asks Composio for the connection's current state and remembers it.",
)
async def get_connection(
    slug: str, principal: PrincipalDep, connections: ToolConnectionServiceDep
) -> ToolResponse:
    return to_tool_response(await connections.refresh_status(principal, slug))


@router.delete(
    "/{slug}/connection",
    response_model=ToolResponse,
    responses={**_AUTH, **_COMPOSIO},
    summary="Disconnect an app",
    description="Removes every connected account of the app in Composio.",
)
async def delete_connection(
    slug: str, principal: PrincipalDep, connections: ToolConnectionServiceDep
) -> ToolResponse:
    return to_tool_response(await connections.disconnect(principal, slug))
