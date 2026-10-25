"""HTTP shapes of memories as their owner manages them in the app: detail with evidence
and history, edits, the review inbox, people, and the data export."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.domain.enums import (
    EntityType,
    MemoryEventAction,
    MemoryType,
    MessageSource,
    SourceRole,
    SuggestionKind,
)
from app.schemas.common import ResponseSchema, StrictSchema
from app.schemas.memory import MemoryEntityResponse, MemoryResponse

_CONTENT = Field(min_length=1, max_length=2000)


def _text(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("must contain text")
    return value


class CreateMemoryRequest(StrictSchema):
    """A memory the user writes. It is saved as accepted."""

    memory_type: MemoryType = MemoryType.NOTE
    content: str = _CONTENT
    sensitive: bool = Field(
        default=False, description="Keep it out of the assistant and every other model."
    )
    due_on: date | None = Field(default=None, description="For a to-do: when it is due.")
    remind_at: datetime | None = Field(
        default=None, description="For a to-do: when to remind, with a timezone; in the future."
    )

    check_text = field_validator("content")(_text)

    @field_validator("remind_at")
    @classmethod
    def remind_at_has_a_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("must include a timezone offset")
        return value


class UpdateMemoryRequest(StrictSchema):
    """Only the fields sent change. New text makes a new version that replaces this one:
    the response is that version, with its own id. ``due_on`` and ``remind_at`` sent as
    null clear them."""

    content: str | None = Field(default=None, min_length=1, max_length=2000)
    memory_type: MemoryType | None = None
    sensitive: bool | None = None
    due_on: date | None = Field(default=None, description="When the item is due.")
    remind_at: datetime | None = Field(
        default=None, description="When to remind the user, with a timezone; in the future."
    )

    check_text = field_validator("content")(_text)

    @field_validator("remind_at")
    @classmethod
    def remind_at_has_a_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("must include a timezone offset")
        return value

    @model_validator(mode="after")
    def must_change_something(self) -> "UpdateMemoryRequest":
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        return self


class OtherMemoryRequest(StrictSchema):
    other_memory_id: uuid.UUID


class AcceptMemoriesRequest(StrictSchema):
    memory_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class AcceptMemoriesResponse(ResponseSchema):
    accepted: int


class DeleteMemoryResponse(ResponseSchema):
    deleted: int = Field(
        description="Memories deleted: this one and those it replaced (older versions, "
        "merged duplicates)."
    )


class DismissSuggestionRequest(StrictSchema):
    first_memory_id: uuid.UUID
    second_memory_id: uuid.UUID
    kind: SuggestionKind


class MyMemorySourceResponse(ResponseSchema):
    """A message the memory rests on."""

    raw_message_id: uuid.UUID
    source_role: SourceRole
    evidence_text: str | None = Field(description="The words of the message it rests on.")
    source: MessageSource
    sent_at: datetime | None
    content: str
    thread_id: uuid.UUID | None = Field(
        description="The chat it was said in, while that chat exists."
    )


class MemoryEventResponse(ResponseSchema):
    id: uuid.UUID
    action: MemoryEventAction
    details: dict[str, Any]
    created_at: datetime


class MemoryVersionResponse(ResponseSchema):
    id: uuid.UUID
    content: str
    created_at: datetime


class MyMemoryDetailResponse(MemoryResponse):
    sources: list[MyMemorySourceResponse]
    entities: list[MemoryEntityResponse]
    history: list[MemoryEventResponse] = Field(description="Oldest first.")
    replaced: list[MemoryVersionResponse] = Field(
        description="Older versions of this memory and memories merged into it or replaced "
        "by it, newest first."
    )
    replaced_by_id: uuid.UUID | None = Field(
        description="When this memory is superseded: the memory that replaced it."
    )


class SuggestionResponse(ResponseSchema):
    kind: SuggestionKind
    first: MemoryResponse = Field(description="The older of the two.")
    second: MemoryResponse
    similarity: float = Field(ge=0, le=1)
    shared_entities: int


class HeldBackMessageResponse(ResponseSchema):
    raw_message_id: uuid.UUID
    content: str
    sent_at: datetime | None
    thread_id: uuid.UUID | None


class HeldBackResponse(ResponseSchema):
    """A message the pipeline would not turn into memories on its own."""

    run_id: uuid.UUID
    held_at: datetime | None
    reason: Literal["unclear", "unreadable"] = Field(
        description="`unclear`: nothing reliable to remember was found. `unreadable`: the "
        "extraction could not be used."
    )
    messages: list[HeldBackMessageResponse]


class ReviewInboxResponse(ResponseSchema):
    proposed_count: int = Field(description="Memories waiting to be accepted.")
    suggestions: list[SuggestionResponse] = Field(
        description="Possible duplicates first, then possible conflicts, most alike first."
    )
    held_back: list[HeldBackResponse] = Field(description="Newest first, up to 30.")
    held_back_count: int


class PersonResponse(ResponseSchema):
    id: uuid.UUID
    entity_type: EntityType
    name: str
    memory_count: int = Field(description="Current memories that mention them.")
    last_seen_at: datetime | None


class PersonDetailResponse(PersonResponse):
    aliases: list[str]
    memories: list[MemoryResponse] = Field(description="Newest first, up to 100.")


class RenamePersonRequest(StrictSchema):
    name: str = Field(min_length=1, max_length=200)

    check_text = field_validator("name")(_text)


class MergePersonRequest(StrictSchema):
    other_person_id: uuid.UUID = Field(description="Merged into this person, then gone.")
