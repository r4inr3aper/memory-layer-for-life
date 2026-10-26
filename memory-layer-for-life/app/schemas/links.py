"""HTTP shapes of the links a user saves for the assistant to share (ADR-050)."""

import uuid
from datetime import datetime

from pydantic import Field, model_validator

from app.domain.enums import LinkKind
from app.schemas.common import ResponseSchema, StrictSchema


class SaveLinkRequest(StrictSchema):
    url: str = Field(
        min_length=1,
        max_length=2000,
        description="A web address; https:// is added when no scheme is given.",
    )
    title: str | None = Field(
        default=None, max_length=200, description="Guessed from the address when not given."
    )
    kind: LinkKind | None = Field(
        default=None,
        description="Guessed from the title and the site when not given. Saving a resume "
        "link makes the previous one a plain link.",
    )


class UpdateLinkRequest(StrictSchema):
    """Only the fields sent change."""

    url: str | None = Field(default=None, min_length=1, max_length=2000)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    kind: LinkKind | None = Field(
        default=None, description="Marking it the resume makes the previous one a plain link."
    )

    @model_validator(mode="after")
    def must_change_something(self) -> "UpdateLinkRequest":
        if self.url is None and self.title is None and self.kind is None:
            raise ValueError("send a url, a title, a kind, or several")
        return self


class LinkResponse(ResponseSchema):
    id: uuid.UUID
    url: str
    title: str
    kind: LinkKind = Field(description="The assistant shares the resume link in job applications.")
    created_at: datetime
    updated_at: datetime


class SavedLinkResponse(LinkResponse):
    created: bool = Field(description="False when the address was saved before.")
