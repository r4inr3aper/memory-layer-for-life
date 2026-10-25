from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse

from app.api.dependencies import (
    AccountServiceDep,
    ExportServiceDep,
    PrincipalDep,
    PushServiceDep,
    UsageServiceDep,
    UserServiceDep,
)
from app.api.v1.app_mappers import to_me_response, to_usage_history_response, to_usage_response
from app.core.exceptions import ErrorResponse
from app.domain.enums import UsageGranularity
from app.schemas.app import (
    AccountDeletionResponse,
    MeResponse,
    RegisterPushTokenRequest,
    UpdateMeRequest,
    UsageHistoryResponse,
    UsageResponse,
)

router = APIRouter()

# FastAPI's type for documented responses.
Responses = dict[int | str, dict[str, Any]]

_AUTH: Responses = {
    401: {"model": ErrorResponse, "description": "No valid access token"},
    503: {"model": ErrorResponse, "description": "User sign-in is not configured"},
}


@router.get("", response_model=MeResponse, responses=_AUTH, summary="Show the signed-in user")
async def get_me(principal: PrincipalDep, users: UserServiceDep) -> MeResponse:
    return to_me_response(await users.get(principal))


@router.patch(
    "",
    response_model=MeResponse,
    responses={**_AUTH, 422: {"model": ErrorResponse, "description": "A value is not valid"}},
    summary="Personalize the assistant or change notifications",
    description='Changes only the fields sent. A text field sent as null or "" is reset.',
)
async def update_me(
    payload: UpdateMeRequest, principal: PrincipalDep, users: UserServiceDep
) -> MeResponse:
    changes = {field: getattr(payload, field) for field in payload.model_fields_set}
    return to_me_response(await users.update_profile(principal, changes))


@router.delete(
    "",
    response_model=AccountDeletionResponse,
    responses={**_AUTH, 502: {"model": ErrorResponse, "description": "Supabase failed"}},
    summary="Delete the account",
    description=(
        "Revokes the user's connected apps, deletes all their data, and deletes their "
        "Supabase sign-in when the API is configured to. Cannot be undone."
    ),
)
async def delete_me(
    principal: PrincipalDep, accounts: AccountServiceDep
) -> AccountDeletionResponse:
    deletion = await accounts.delete(principal)
    return AccountDeletionResponse(
        apps_disconnected=deletion.apps_disconnected,
        apps_not_disconnected=deletion.apps_not_disconnected,
        identity_deleted=deletion.identity_deleted,
    )


@router.get(
    "/usage",
    response_model=UsageResponse,
    responses=_AUTH,
    summary="Show today's usage",
    description=(
        "Prompts (chat messages and scheduled runs) used today against the daily limit, "
        "with tokens and estimated cost. The day is the UTC calendar day."
    ),
)
async def get_usage(principal: PrincipalDep, usage: UsageServiceDep) -> UsageResponse:
    return to_usage_response(await usage.report(principal))


@router.get(
    "/usage/history",
    response_model=UsageHistoryResponse,
    responses=_AUTH,
    summary="Show prompts and cost over time",
    description=(
        "Per day (the last 14), week (the last 12), or month (the last 12), oldest first. "
        "Periods are UTC; weeks start on Monday."
    ),
)
async def get_usage_history(
    principal: PrincipalDep,
    usage: UsageServiceDep,
    granularity: Annotated[UsageGranularity, Query()] = UsageGranularity.DAY,
) -> UsageHistoryResponse:
    return to_usage_history_response(await usage.history(principal, granularity))


@router.get(
    "/export",
    responses={
        **_AUTH,
        200: {
            "content": {"application/json": {}},
            "description": "Everything the app holds for the user, as one JSON file",
        },
    },
    summary="Export my data",
    description=(
        "The account and assistant settings, every memory (sensitive ones included and "
        "marked) with its evidence and history, the people in them, every chat, schedules "
        "with their runs, connected apps (never their credentials), and daily usage. Sent as "
        "an attachment."
    ),
)
async def export_my_data(principal: PrincipalDep, exports: ExportServiceDep) -> JSONResponse:
    document = await exports.export(principal)
    day = str(document["exported_at"])[:10]
    return JSONResponse(
        document,
        headers={"Content-Disposition": f'attachment; filename="muse-export-{day}.json"'},
    )


@router.post(
    "/push-tokens",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_AUTH,
    summary="Register a device for push notifications",
    description="Idempotent. A token already registered moves to this user.",
)
async def register_push_token(
    payload: RegisterPushTokenRequest, principal: PrincipalDep, push: PushServiceDep
) -> Response:
    await push.register(principal, payload.token, payload.platform)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/push-tokens/{token}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_AUTH,
    summary="Stop push notifications to a device",
)
async def unregister_push_token(
    token: str, principal: PrincipalDep, push: PushServiceDep
) -> Response:
    await push.unregister(principal, token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
