"""HTTP shapes of the documents a user uploads for the assistant to read (ADR-049)."""

import uuid
from datetime import datetime
from typing import Final

from pydantic import Field, field_validator, model_validator

from app.domain.documents import DOCUMENT_TYPES
from app.domain.enums import DocumentExtraction
from app.schemas.common import ResponseSchema, StrictSchema

# Base64 of the largest document the API could be configured to accept, with headroom. The
# configured limit (DOCUMENT_MAX_BYTES) is checked on the decoded bytes.
_MAX_DOCUMENT_BASE64_CHARS: Final = 30_000_000


class DocumentUploadRequest(StrictSchema):
    name: str = Field(min_length=1, max_length=255, description="The file name.")
    media_type: str = Field(
        description="application/pdf, a Word document "
        "(application/vnd.openxmlformats-officedocument.wordprocessingml.document), "
        "text/plain, or text/markdown."
    )
    data: str = Field(max_length=_MAX_DOCUMENT_BASE64_CHARS, description="Base64 content.")

    @field_validator("media_type")
    @classmethod
    def media_type_must_be_supported(cls, value: str) -> str:
        if value not in DOCUMENT_TYPES:
            raise ValueError("upload a PDF, a Word document (.docx), or a text file")
        return value


class UpdateDocumentRequest(StrictSchema):
    """Only the fields sent change."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    is_resume: bool | None = Field(
        default=None, description="Mark it as the user's resume; the previous one is unmarked."
    )

    @model_validator(mode="after")
    def must_change_something(self) -> "UpdateDocumentRequest":
        if self.title is None and self.is_resume is None:
            raise ValueError("send a title, is_resume, or both")
        return self


class DocumentResponse(ResponseSchema):
    id: uuid.UUID
    title: str
    file_name: str
    media_type: str
    size_bytes: int
    is_resume: bool = Field(
        description="The assistant uses it for applications and questions about the user's work."
    )
    extraction: DocumentExtraction = Field(
        description="How the text was read: the PDF's text layer, a Word document's "
        "paragraphs, a text file as it is, or a scan read by the model."
    )
    text_chars: int = Field(description="Characters of text kept.")
    page_count: int | None
    has_file: bool = Field(
        description="Whether the original file is kept, so the assistant can attach it to "
        "an email and the app can open it. False for documents uploaded before files were "
        "kept: uploading the same file again keeps it."
    )
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(DocumentResponse):
    created: bool = Field(description="False when the same file was uploaded before.")


class DocumentDetailResponse(DocumentResponse):
    text: str = Field(description="The text the assistant reads, as kept.")


class DocumentFileResponse(ResponseSchema):
    name: str = Field(description="The file name.")
    media_type: str
    data: str = Field(description="Base64 content.")
