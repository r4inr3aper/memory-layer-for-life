import uuid
from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, Field, field_validator

from app.core.config import EffortLevel, is_known_timezone
from app.domain.enums import PlaygroundRunStatus
from app.schemas.common import ResponseSchema, StrictSchema
from app.schemas.llm_call import LlmCallResponse


class PlaygroundMessageInput(StrictSchema):
    text: str = Field(min_length=1)
    sent_at: AwareDatetime | None = Field(
        default=None,
        description="When the message was written. Needed to read words like 'tomorrow'.",
    )


class PlaygroundRunRequest(StrictSchema):
    """One test call. Nothing it produces is stored as a raw message or a memory."""

    messages: list[PlaygroundMessageInput] = Field(min_length=1)
    model: str | None = Field(default=None, description="Defaults to the configured model.")
    effort: EffortLevel | None = None
    timezone: str | None = Field(default=None, description="IANA timezone of the writer.")

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and not is_known_timezone(value):
            raise ValueError("timezone is not a known IANA timezone")
        return value


class PlaygroundMessageResponse(ResponseSchema):
    index: int
    text: str
    sent_at: datetime | None


class PlaygroundRunSummaryResponse(ResponseSchema):
    id: uuid.UUID
    status: PlaygroundRunStatus
    requested_model: str
    effort: str
    message_count: int
    preview: str = Field(description="The start of the first message.")
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


class PlaygroundRunResponse(ResponseSchema):
    id: uuid.UUID
    status: PlaygroundRunStatus
    messages: list[PlaygroundMessageResponse]
    timezone_name: str | None
    requested_model: str
    effort: str
    output: dict[str, Any] | None = Field(
        description="The validated extraction, after the checks the pipeline applies."
    )
    raw_output: str | None = Field(description="The text the model returned, as it came.")
    corrections: list[str] = Field(description="What the system changed in the output.")
    error_code: str | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None
    call: LlmCallResponse | None = Field(description="The model call this test made.")


class ExtractionContractResponse(ResponseSchema):
    """The format an extraction must have, for comparing with a test call's output."""

    schema_version: str
    prompt_version: str
    pipeline_version: str
    output_schema: dict[str, Any] = Field(description="JSON Schema of the validated output.")
    provider_schema: dict[str, Any] = Field(
        description="JSON Schema sent to the provider to constrain generation."
    )
