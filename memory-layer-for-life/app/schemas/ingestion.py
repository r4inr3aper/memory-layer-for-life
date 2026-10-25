import uuid
from datetime import datetime

from pydantic import Field

from app.domain.enums import MessageSource, ProcessingStatus
from app.schemas.common import ResponseSchema, StrictSchema
from app.schemas.raw_message import RawMessageCreate


class IngestUnitRequest(StrictSchema):
    """One processing unit: messages that belong together and are read together.

    Order matters and is preserved. A single thought sent as one message is a unit of one.
    """

    messages: list[RawMessageCreate] = Field(min_length=1)


class IngestBatchRequest(StrictSchema):
    units: list[IngestUnitRequest] = Field(min_length=1)


class IngestedMessageResponse(ResponseSchema):
    id: uuid.UUID
    source: MessageSource
    source_message_id: str | None
    ingested_at: datetime
    created: bool = Field(description="False when this delivery matched a stored message.")


class IngestedRunResponse(ResponseSchema):
    id: uuid.UUID
    status: ProcessingStatus
    pipeline_version: str
    attempt_number: int
    created: bool = Field(description="False when this unit already had a run for this version.")


class IngestUnitResponse(ResponseSchema):
    messages: list[IngestedMessageResponse]
    processing_run: IngestedRunResponse


class IngestBatchResponse(ResponseSchema):
    units: list[IngestUnitResponse]
