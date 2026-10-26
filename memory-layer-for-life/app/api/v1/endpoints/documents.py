"""The signed-in user's documents: files the assistant reads when relevant (ADR-049) and
attaches to emails (ADR-050)."""

import base64
import uuid
from typing import Any

from fastapi import APIRouter, Response, status

from app.api.dependencies import DocumentServiceDep, PrincipalDep
from app.core.exceptions import ErrorResponse
from app.schemas.documents import (
    DocumentDetailResponse,
    DocumentFileResponse,
    DocumentResponse,
    DocumentUploadRequest,
    DocumentUploadResponse,
    UpdateDocumentRequest,
)
from app.services.documents import DocumentView

router = APIRouter()

Responses = dict[int | str, dict[str, Any]]

_AUTH: Responses = {
    401: {"model": ErrorResponse, "description": "No valid access token"},
    503: {"model": ErrorResponse, "description": "User sign-in is not configured"},
}
_NOT_FOUND: Responses = {404: {"model": ErrorResponse, "description": "No such document"}}


def _response(view: DocumentView) -> DocumentResponse:
    return DocumentResponse.model_validate(view)


@router.get(
    "",
    response_model=list[DocumentResponse],
    responses=_AUTH,
    summary="List my documents",
    description="The resume first, then the most recently changed.",
)
async def list_documents(
    principal: PrincipalDep, documents: DocumentServiceDep
) -> list[DocumentResponse]:
    return [_response(view) for view in await documents.list_documents(principal)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentUploadResponse,
    responses={
        **_AUTH,
        413: {"model": ErrorResponse, "description": "The user's file storage is full"},
        422: {"model": ErrorResponse, "description": "Unsupported, too large, or no text"},
        429: {
            "model": ErrorResponse,
            "description": "Daily prompt limit (scans read by the model)",
        },
    },
    summary="Upload a document",
    description=(
        "Reads the text of a PDF, a Word document, or a text file for the assistant, and "
        "keeps the file so the assistant can attach it to an email. The same file again "
        "returns the stored document, keeping its file if only its text was kept before. A "
        "document that looks like a resume becomes the user's resume when they have none."
    ),
)
async def upload_document(
    payload: DocumentUploadRequest, principal: PrincipalDep, documents: DocumentServiceDep
) -> DocumentUploadResponse:
    upload = await documents.upload(
        principal,
        file_name=payload.name,
        media_type=payload.media_type,
        data_base64=payload.data,
    )
    return DocumentUploadResponse(**_response(upload.document).model_dump(), created=upload.created)


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    responses={**_AUTH, **_NOT_FOUND},
    summary="Show a document and its text",
)
async def get_document(
    document_id: uuid.UUID, principal: PrincipalDep, documents: DocumentServiceDep
) -> DocumentDetailResponse:
    detail = await documents.detail(principal, document_id)
    return DocumentDetailResponse(**_response(detail.document).model_dump(), text=detail.text)


@router.get(
    "/{document_id}/file",
    response_model=DocumentFileResponse,
    responses={
        **_AUTH,
        404: {"model": ErrorResponse, "description": "No such document, or no file kept"},
    },
    summary="Download a document's file",
    description="The original file, to open or share. Documents uploaded before files "
    "were kept have none.",
)
async def get_document_file(
    document_id: uuid.UUID, principal: PrincipalDep, documents: DocumentServiceDep
) -> DocumentFileResponse:
    stored = await documents.stored_file(principal, document_id)
    return DocumentFileResponse(
        name=stored.document.file_name,
        media_type=stored.document.media_type,
        data=base64.b64encode(stored.data).decode("ascii"),
    )


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
    responses={**_AUTH, **_NOT_FOUND},
    summary="Rename a document, or mark it as my resume",
)
async def update_document(
    document_id: uuid.UUID,
    payload: UpdateDocumentRequest,
    principal: PrincipalDep,
    documents: DocumentServiceDep,
) -> DocumentResponse:
    return _response(
        await documents.update(
            principal, document_id, title=payload.title, is_resume=payload.is_resume
        )
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_AUTH, **_NOT_FOUND},
    summary="Delete a document",
    description="Deletes the document, its text, and its file; the assistant can no longer "
    "read or attach it.",
)
async def delete_document(
    document_id: uuid.UUID, principal: PrincipalDep, documents: DocumentServiceDep
) -> Response:
    await documents.delete(principal, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
