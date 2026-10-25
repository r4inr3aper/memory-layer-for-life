"""HTTP shapes of insights and feedback on them."""

import uuid

from pydantic import Field

from app.domain.enums import InsightKind, InsightTarget
from app.schemas.common import ResponseSchema, StrictSchema


class InsightResponse(ResponseSchema):
    key: str = Field(description="Names the insight and its period; send it back as feedback.")
    kind: InsightKind
    title: str
    body: str
    memory_ids: list[uuid.UUID] = Field(description="The memories it rests on.")
    target: InsightTarget = Field(description="What opening it shows.")
    target_id: uuid.UUID | None = Field(description="The person or memory, when it names one.")


class InsightsResponse(ResponseSchema):
    items: list[InsightResponse] = Field(description="Strongest first.")


class InsightFeedbackRequest(StrictSchema):
    key: str = Field(min_length=1, max_length=200)
    kind: InsightKind
    useful: bool = Field(description="False hides the insight for its period.")


class InsightUsefulnessResponse(ResponseSchema):
    kind: InsightKind
    useful: int
    not_useful: int
