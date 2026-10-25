import uuid
from datetime import datetime
from typing import Self

from pydantic import Field, model_validator

from app.domain.enums import (
    ExtractionDisposition,
    ExtractionStatus,
    PipelineStage,
    ProcessingStatus,
    ReplayAction,
    RunEventType,
)
from app.schemas.common import ResponseSchema, StrictSchema


class ProcessingRunResponse(ResponseSchema):
    id: uuid.UUID
    status: ProcessingStatus
    pipeline_version: str
    attempt_number: int
    raw_message_ids: list[uuid.UUID] = Field(description="The unit, in processing order.")
    available_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime


class ProcessingRunEventResponse(ResponseSchema):
    id: uuid.UUID
    attempt_number: int
    event_type: RunEventType
    stage: PipelineStage | None
    error_code: str | None
    detail: str | None
    created_at: datetime


class ExtractionSummaryResponse(ResponseSchema):
    id: uuid.UUID
    schema_version: str
    extractor_version: str
    model_name: str | None
    status: ExtractionStatus
    disposition: ExtractionDisposition | None


class ProcessingRunDetailResponse(ProcessingRunResponse):
    events: list[ProcessingRunEventResponse]
    extraction: ExtractionSummaryResponse | None
    memory_ids: list[uuid.UUID]


class ReplayRequest(StrictSchema):
    """Selects which units to reprocess under the current pipeline configuration.

    Exactly one selector must be given. Replay never creates a raw message: it only
    ensures each selected unit has a run for the current configuration.
    """

    raw_message_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=500)
    run_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=500)
    all_units: bool = False
    limit: int = Field(default=100, ge=1, le=500)

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> Self:
        selectors = [
            self.raw_message_ids is not None,
            self.run_ids is not None,
            self.all_units,
        ]
        if sum(selectors) != 1:
            raise ValueError("Provide exactly one of raw_message_ids, run_ids, or all_units.")
        return self


class ReplayOutcomeResponse(ResponseSchema):
    action: ReplayAction
    processing_run: ProcessingRunResponse


class ReplayResponse(ResponseSchema):
    outcomes: list[ReplayOutcomeResponse]
