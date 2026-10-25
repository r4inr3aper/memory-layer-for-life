import uuid
from datetime import datetime
from typing import Any, Self

from pydantic import Field, model_validator

from app.domain.enums import EntityStatus, EntityType
from app.schemas.common import ResponseSchema, StrictSchema


class EntityCreate(StrictSchema):
    entity_type: EntityType
    canonical_name: str = Field(min_length=1)
    description: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class EntityResponse(ResponseSchema):
    id: uuid.UUID
    entity_type: EntityType
    canonical_name: str
    normalized_name: str
    description: str | None
    status: EntityStatus
    merged_into_id: uuid.UUID | None
    attributes: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class EntityMentionCreate(StrictSchema):
    entity_type: EntityType
    mention_text: str = Field(min_length=1)
    start_offset: int | None = None
    end_offset: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("start_offset and end_offset must be both present or both absent")
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("end_offset must be greater than or equal to start_offset")
        return self
