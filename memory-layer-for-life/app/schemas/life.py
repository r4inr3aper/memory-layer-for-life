"""HTTP shapes of life state, the daily brief, and searching one's chats."""

import uuid
from datetime import date, datetime

from pydantic import Field

from app.domain.enums import ChatRole, ThreadKind
from app.schemas.common import ResponseSchema, StrictSchema
from app.schemas.memory import MemoryResponse


class LifeOverviewResponse(ResponseSchema):
    """What is open in the user's life now. Items are memories; each list is soonest due
    first, then oldest."""

    today: date = Field(description="The user's local date.")
    timezone: str
    overdue: list[MemoryResponse]
    due_today: list[MemoryResponse]
    upcoming: list[MemoryResponse] = Field(description="Due in the next seven days.")
    later: list[MemoryResponse]
    someday: list[MemoryResponse] = Field(description="No due date.")
    goals: list[MemoryResponse] = Field(description="Goals and projects.")
    stale_ids: list[uuid.UUID] = Field(
        description="Open items nobody touched for two weeks and not due in the future."
    )
    reminders: list[MemoryResponse] = Field(description="Pending reminders, soonest first.")
    recently_done: list[MemoryResponse] = Field(description="Done in the last seven days.")
    questions: list[MemoryResponse] = Field(
        default_factory=list,
        description="Open questions and unresolved problems: open, but nothing to tick off.",
    )
    triage: list[MemoryResponse] = Field(
        default_factory=list,
        description="Open items from an imported chat that nobody has looked at yet: keep "
        "(accept), done, or drop. They are not in the lists above until kept.",
    )


class BriefItemResponse(ResponseSchema):
    memory_id: uuid.UUID
    content: str
    due_on: date | None


class BriefResponse(ResponseSchema):
    """Today's brief as it stands now. Sensitive memories are never in it."""

    text: str = Field(description="Markdown, as posted to chat.")
    summary: str
    follow_ups: list[BriefItemResponse] = Field(
        description="Due yesterday and still open: did they get done?"
    )
    nothing_to_say: bool


class MessageSearchRequest(StrictSchema):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=20, ge=1, le=50)


class MessageHitResponse(ResponseSchema):
    message_id: uuid.UUID
    thread_id: uuid.UUID
    thread_title: str
    thread_kind: ThreadKind
    role: ChatRole
    snippet: str = Field(description="The best passage; matches are wrapped in << and >>.")
    created_at: datetime


class MessageSearchResponse(ResponseSchema):
    query: str
    items: list[MessageHitResponse]


class PromiseResponse(ResponseSchema):
    memory: MemoryResponse
    people: list[str] = Field(description="The people it involves.")


class MeetingResponse(ResponseSchema):
    event: MemoryResponse = Field(description="A calendar event of today or tomorrow.")
    people: list[str] = Field(description="The user's people the event names.")
    related: list[MemoryResponse] = Field(
        description="What the user's memories say about them, newest first."
    )


class TodayResponse(ResponseSchema):
    """The Feed's cards: each something to act on, computed without a model (ADR-048)."""

    today: date = Field(description="The user's local date.")
    timezone: str
    next_actions: list[MemoryResponse] = Field(
        description="Overdue, due or reminded today, promises to people, then due this "
        "week; at most five, most pressing first."
    )
    promises: list[PromiseResponse] = Field(
        description="Other open items that involve a person, at most three."
    )
    meetings: list[MeetingResponse] = Field(description="Calendar events of today and tomorrow.")
    resurface: MemoryResponse | None = Field(
        description="An idea, intention, or goal noted weeks ago and untouched since: still on?"
    )
    to_confirm: list[MemoryResponse] = Field(
        description="The newest memories the pipeline was unsure of, at most three."
    )
    review_count: int = Field(description="Memories made in the last week that wait for review.")
