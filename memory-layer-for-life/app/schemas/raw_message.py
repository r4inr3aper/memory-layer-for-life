import uuid
from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, Field, JsonValue, field_validator

from app.domain.enums import MessageSource
from app.schemas.common import ResponseSchema, StrictSchema


class RawMessageCreate(StrictSchema):
    """Source envelope of one incoming message.

    ``source_message_id`` is the identity the source gives the message. Sending it makes
    delivery idempotent: the same id with the same content is accepted again without
    creating a second message. Without it every delivery is a new message, because
    identical text can legitimately be two separate messages.
    """

    source: MessageSource
    content: str = Field(min_length=1)
    source_message_id: str | None = Field(default=None, min_length=1, max_length=255)
    source_created_at: AwareDatetime | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must contain something other than whitespace")
        return value


class RawMessageResponse(ResponseSchema):
    id: uuid.UUID
    source: MessageSource
    source_message_id: str | None
    content: str
    content_sha256: str
    source_created_at: datetime | None
    ingested_at: datetime
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
