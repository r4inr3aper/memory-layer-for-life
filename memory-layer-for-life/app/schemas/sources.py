"""HTTP shapes of new memory sources: chat imports, files, and connected apps."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from app.domain.enums import ImportStatus
from app.schemas.common import ResponseSchema, StrictSchema


class ImportPreviewRequest(StrictSchema):
    file_name: str = Field(min_length=1, max_length=255)
    data_base64: str = Field(min_length=1, description="The export (.txt or .zip), base64.")


class ImportStartRequest(StrictSchema):
    me: str = Field(min_length=1, max_length=200, description="Which participant is the user.")
    since: date | None = Field(default=None, description="Leave out what came before.")
    only_my_conversations: bool = Field(
        default=True, description="Keep only conversations the user took part in."
    )
    max_conversations: int = Field(
        default=200, ge=1, le=300, description="The most recent are kept. Each is one extraction."
    )


class ImportParticipantResponse(ResponseSchema):
    name: str
    messages: int
    conversations: int = Field(description="Conversations this person took part in.")


class ImportProgressResponse(ResponseSchema):
    done: int
    failed: int
    waiting: int
    memories: int


class ImportResponse(ResponseSchema):
    id: uuid.UUID
    file_name: str
    status: ImportStatus
    participants: list[ImportParticipantResponse] = Field(description="Most messages first.")
    message_count: int
    all_conversations: int
    first_message_at: datetime | None
    last_message_at: datetime | None
    owner_name: str | None
    since: date | None
    unit_count: int | None = Field(description="Conversations queued, once started.")
    cost_per_conversation: Decimal | None = Field(
        description="Estimated cost of one extraction in `currency`; null when unknown."
    )
    currency: str
    progress: ImportProgressResponse | None
    created_at: datetime


class FileMemoryRequest(StrictSchema):
    file_name: str = Field(min_length=1, max_length=255)
    media_type: str = Field(
        description="image/jpeg, image/png, image/gif, image/webp, or application/pdf."
    )
    data_base64: str = Field(min_length=1)


class FileMemoryResponse(ResponseSchema):
    raw_message_id: uuid.UUID
    processing_run_id: uuid.UUID
    text: str = Field(description="What was read from the file; memories are made from it.")
    created: bool = Field(description="False when the same file was given before.")


class SourceResponse(ResponseSchema):
    app: str
    connected: bool
    enabled: bool = Field(description="Whether its items become memories.")
    last_synced_at: datetime | None
    error: str | None = Field(description="Why the last sync failed, to show to the user.")


class SourceUpdateRequest(StrictSchema):
    enabled: bool
