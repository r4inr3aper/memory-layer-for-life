"""New memory sources for the signed-in user: WhatsApp imports, photos and PDFs, and
connected apps such as their calendar."""

import uuid
from typing import Any

from fastapi import APIRouter, status

from app.api.dependencies import (
    FileCaptureDep,
    ImportServiceDep,
    PrincipalDep,
    SourceSyncServiceDep,
)
from app.core.exceptions import ErrorResponse
from app.schemas.sources import (
    FileMemoryRequest,
    FileMemoryResponse,
    ImportParticipantResponse,
    ImportPreviewRequest,
    ImportProgressResponse,
    ImportResponse,
    ImportStartRequest,
    SourceResponse,
    SourceUpdateRequest,
)
from app.services.imports import ImportView

router = APIRouter()

Responses = dict[int | str, dict[str, Any]]

_AUTH: Responses = {
    401: {"model": ErrorResponse, "description": "No valid access token"},
    503: {"model": ErrorResponse, "description": "User sign-in is not configured"},
}
_INVALID: Responses = {422: {"model": ErrorResponse, "description": "Not a file that can be used"}}


def _import(view: ImportView) -> ImportResponse:
    return ImportResponse(
        id=view.id,
        file_name=view.file_name,
        status=view.status,
        participants=[ImportParticipantResponse.model_validate(p) for p in view.participants],
        message_count=view.message_count,
        all_conversations=view.all_conversations,
        first_message_at=view.first_message_at,
        last_message_at=view.last_message_at,
        owner_name=view.owner_name,
        since=view.since,
        unit_count=view.unit_count,
        cost_per_conversation=view.cost_per_conversation,
        currency=view.currency,
        progress=(ImportProgressResponse.model_validate(view.progress) if view.progress else None),
        created_at=view.created_at,
    )


@router.post(
    "/imports/whatsapp",
    status_code=status.HTTP_201_CREATED,
    response_model=ImportResponse,
    responses={**_AUTH, **_INVALID},
    summary="Read a WhatsApp chat export",
    description=(
        "Reads the export (the .txt, or the .zip WhatsApp makes) and returns its "
        "participants and what an import would cost. Nothing is imported until it is "
        "started. The same file again returns the same import."
    ),
)
async def preview_import(
    payload: ImportPreviewRequest, principal: PrincipalDep, imports: ImportServiceDep
) -> ImportResponse:
    return _import(await imports.preview(principal, payload.file_name, payload.data_base64))


@router.post(
    "/imports/{import_id}/start",
    response_model=ImportResponse,
    responses={**_AUTH, **_INVALID, 404: {"model": ErrorResponse, "description": "No such import"}},
    summary="Import a chat's conversations as memories",
    description=(
        "Each conversation (messages less than 30 minutes apart) becomes one unit of the "
        "user's evidence and is processed in the background: one extraction each."
    ),
)
async def start_import(
    import_id: uuid.UUID,
    payload: ImportStartRequest,
    principal: PrincipalDep,
    imports: ImportServiceDep,
) -> ImportResponse:
    started = await imports.start(
        principal,
        import_id,
        me=payload.me,
        since=payload.since,
        only_mine=payload.only_my_conversations,
        max_conversations=payload.max_conversations,
    )
    return _import(started)


@router.get(
    "/imports",
    response_model=list[ImportResponse],
    responses=_AUTH,
    summary="List my imports with their progress",
)
async def list_imports(principal: PrincipalDep, imports: ImportServiceDep) -> list[ImportResponse]:
    return [_import(view) for view in await imports.list_imports(principal)]


@router.get(
    "/imports/{import_id}",
    response_model=ImportResponse,
    responses={**_AUTH, 404: {"model": ErrorResponse, "description": "No such import"}},
    summary="Show an import's progress",
)
async def get_import(
    import_id: uuid.UUID, principal: PrincipalDep, imports: ImportServiceDep
) -> ImportResponse:
    return _import(await imports.get(principal, import_id))


@router.post(
    "/memories/from-file",
    status_code=status.HTTP_201_CREATED,
    response_model=FileMemoryResponse,
    responses={
        **_AUTH,
        **_INVALID,
        429: {"model": ErrorResponse, "description": "Today's prompts are used up"},
        502: {"model": ErrorResponse, "description": "The file could not be read"},
    },
    summary="Remember a photo or a PDF",
    description=(
        "Reads the file's text (one model call, counted as one of today's prompts) and "
        "keeps it as the user's evidence; memories are made from it in the background. "
        "The file itself is not kept."
    ),
)
async def memory_from_file(
    payload: FileMemoryRequest, principal: PrincipalDep, files: FileCaptureDep
) -> FileMemoryResponse:
    result = await files.capture(
        principal,
        file_name=payload.file_name,
        media_type=payload.media_type,
        data_base64=payload.data_base64,
    )
    return FileMemoryResponse(
        raw_message_id=result.raw_message_id,
        processing_run_id=result.processing_run_id,
        text=result.text,
        created=result.created,
    )


@router.get(
    "/sources",
    response_model=list[SourceResponse],
    responses=_AUTH,
    summary="List the apps that can become memory sources",
)
async def list_sources(
    principal: PrincipalDep, sources: SourceSyncServiceDep
) -> list[SourceResponse]:
    return [SourceResponse.model_validate(view) for view in await sources.sources(principal)]


@router.patch(
    "/sources/{app}",
    response_model=SourceResponse,
    responses={**_AUTH, **_INVALID},
    summary="Use an app as a memory source, or stop",
    description="Turning it on syncs at once: upcoming calendar events become plans.",
)
async def update_source(
    app: str, payload: SourceUpdateRequest, principal: PrincipalDep, sources: SourceSyncServiceDep
) -> SourceResponse:
    view = await sources.set_enabled(principal, app, enabled=payload.enabled)
    return SourceResponse.model_validate(view)


@router.post(
    "/sources/{app}/sync",
    response_model=SourceResponse,
    responses={**_AUTH, **_INVALID},
    summary="Sync an app now",
)
async def sync_source(
    app: str, principal: PrincipalDep, sources: SourceSyncServiceDep
) -> SourceResponse:
    await sources.sync(principal, app)
    return SourceResponse.model_validate((await sources.sources_by_app(principal))[app])
