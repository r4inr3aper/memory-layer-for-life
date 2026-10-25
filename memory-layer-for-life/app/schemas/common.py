import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StrictSchema(BaseModel):
    """Base for inbound payloads: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class ResponseSchema(BaseModel):
    """Base for outbound payloads built from ORM objects or service results."""

    model_config = ConfigDict(from_attributes=True)


class TimestampResponse(ResponseSchema):
    created_at: datetime


class UpdateTimestampResponse(TimestampResponse):
    updated_at: datetime


class UUIDResponse(ResponseSchema):
    id: uuid.UUID


class PageParams(StrictSchema):
    """Offset pagination shared by collection endpoints."""

    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class Page[ItemT](ResponseSchema):
    items: list[ItemT]
    total: int
    limit: int
    offset: int
