import uuid
from datetime import date, datetime
from typing import Any

from pydantic import Field

from app.domain.enums import (
    CloseReason,
    EntityType,
    MemoryEntityRelation,
    MemoryOrigin,
    MemoryState,
    MemoryStatus,
    MemoryType,
    MessageSource,
    SourceRole,
)
from app.schemas.common import ResponseSchema, StrictSchema


class MemoryCreate(StrictSchema):
    memory_type: MemoryType
    content: str = Field(min_length=1)
    status: MemoryStatus = MemoryStatus.PROPOSED
    confidence: float | None = Field(default=None, ge=0, le=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    observed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryResponse(ResponseSchema):
    id: uuid.UUID
    memory_type: MemoryType
    content: str
    normalized_content: str | None
    status: MemoryStatus
    confidence: float | None
    valid_from: datetime | None
    valid_until: datetime | None
    observed_at: datetime | None
    supersedes_memory_id: uuid.UUID | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    created_by: MemoryOrigin = Field(
        description="Who wrote the text: the memory pipeline, or the user (by hand or by "
        "correcting a memory)."
    )
    sensitive: bool = Field(
        description="Health, feelings, or other private matters. Shown to the user, never "
        "given to the assistant or any other model."
    )
    state: MemoryState | None = Field(
        default=None, description="Whether what it describes is open, planned, or done."
    )
    due_on: date | None = Field(default=None, description="When an item is due.")
    remind_at: datetime | None = Field(
        default=None, description="When the user is reminded; cleared once sent."
    )
    closed_at: datetime | None = Field(default=None, description="When an item was closed.")
    close_reason: CloseReason | None = None


class MemorySourceResponse(ResponseSchema):
    """One piece of evidence behind a memory, with the original message it points to."""

    raw_message_id: uuid.UUID
    extraction_result_id: uuid.UUID | None = Field(
        description="Empty when the user, not an extraction, tied the message to the memory."
    )
    processing_run_id: uuid.UUID | None
    source_role: SourceRole
    evidence_text: str | None
    source: MessageSource
    source_message_id: str | None
    source_created_at: datetime | None
    content: str


class MemoryEntityResponse(ResponseSchema):
    entity_id: uuid.UUID
    entity_type: EntityType
    canonical_name: str
    relationship_type: MemoryEntityRelation


class MemoryDetailResponse(MemoryResponse):
    sources: list[MemorySourceResponse]
    entities: list[MemoryEntityResponse]
