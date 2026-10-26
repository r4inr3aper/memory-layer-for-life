"""Validated shape of ``chat_messages.metadata``: what the app shows beside a message.

JSONB holds these because a message carries at most a few of them and they evolve with
the app. It is still a contract: the server writes this model and the API returns it.
"""

import uuid
from datetime import date, datetime

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.enums import (
    ProposalStatus,
    ScheduleDelivery,
    ScheduleFrequency,
    ScheduleRunStatus,
    Weekday,
)

logger = structlog.get_logger(__name__)


class MetadataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrowserPreview(MetadataModel):
    """A cloud browser the assistant used. ``live_view_url`` shows it as it runs."""

    run_id: str
    session_id: str | None = None
    live_view_url: str | None = None
    task: str
    status: str = Field(description="running, completed, failed, or login_required.")


class ConnectLink(MetadataModel):
    """An app the user has to connect before the assistant can use it."""

    toolkit: str
    tool_name: str
    connect_url: str


class DraftAttachment(MetadataModel):
    """One of the user's files attached to a draft (ADR-050). ``send_arguments`` refer to
    it by ``document_id``; the file is staged when the user taps Send."""

    document_id: uuid.UUID
    title: str
    file_name: str
    media_type: str
    size_bytes: int


class JobApplicationDraft(MetadataModel):
    """A review card for a job application email the assistant prepared.

    The card lets the user send with one tap. The backend executes the stored
    app action only after that explicit button press.
    """

    # The job post the draft answers, when there is one (a LinkedIn post, a job page).
    linkedin_post_url: str | None = None
    recipient_email: str
    subject: str
    body: str
    company: str | None = None
    role_title: str | None = None
    delivery_app: str = Field(description="The connected app that sends it, usually gmail.")
    send_tool_slug: str = Field(description="Composio tool slug used to send the email.")
    send_arguments: dict[str, object] = Field(default_factory=dict)
    attachments: list[DraftAttachment] = Field(
        default_factory=list, description="The user's files sent with the email."
    )
    status: str = Field(description="pending, sending, sent, failed, or dismissed.")
    error_message: str | None = None
    sent_at: datetime | None = None


class ScheduleProposal(MetadataModel):
    """A schedule the assistant proposed. It exists only once the user confirms it.

    The rule fields mirror ``app.domain.schedule_rules``. Proposals stored before
    scheduling v2 name a single ``weekday``; ``rule_weekdays`` reads either form.
    """

    title: str
    original_prompt: str
    task: str
    frequency: ScheduleFrequency
    local_time: str = Field(description="HH:MM, 24-hour, in the schedule's timezone.")
    weekdays: list[Weekday] | None = None
    weekday: Weekday | None = Field(default=None, description="Older proposals only.")
    day_of_month: int | None = None
    start_date: date | None = None
    interval_hours: int | None = None
    timezone: str
    delivery: ScheduleDelivery
    delivery_target: str | None = None
    summary: str
    status: ProposalStatus = ProposalStatus.PENDING
    scheduled_task_id: uuid.UUID | None = None

    def rule_weekdays(self) -> tuple[Weekday, ...]:
        if self.weekdays:
            return tuple(self.weekdays)
        return (self.weekday,) if self.weekday is not None else ()


class AttachmentNote(MetadataModel):
    """A file sent with a user message. The file itself is not kept: the model reads it
    in the turn it was sent, and later turns see only this note."""

    name: str
    media_type: str
    size_bytes: int


class ScheduledRunNote(MetadataModel):
    """Marks a message that delivered the result of a scheduled run."""

    scheduled_task_id: uuid.UUID
    run_id: uuid.UUID
    status: ScheduleRunStatus


class ReminderNote(MetadataModel):
    """Marks a reminder the user set, so the app offers Done and Snooze beside it. The text
    of a sensitive one is not in the message: chat history reaches the assistant."""

    memory_id: uuid.UUID
    sensitive: bool = False


class BriefItemNote(MetadataModel):
    memory_id: uuid.UUID
    content: str


class BriefNote(MetadataModel):
    """Marks a daily brief. ``follow_ups`` are the items it asks about (due yesterday,
    still open), so the app offers Done and Not yet beside each."""

    day: date
    follow_ups: list[BriefItemNote] = Field(default_factory=list)


class MessageMetadata(MetadataModel):
    browser_preview: BrowserPreview | None = None
    connect_link: ConnectLink | None = None
    job_application_draft: JobApplicationDraft | None = None
    schedule_proposal: ScheduleProposal | None = None
    scheduled_run: ScheduledRunNote | None = None
    attachments: list[AttachmentNote] | None = None
    reminder: ReminderNote | None = None
    brief: BriefNote | None = None

    def to_json(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def from_json(cls, data: object) -> "MessageMetadata":
        """Read stored metadata. A row that no longer fits the contract shows no cards."""
        try:
            return cls.model_validate(data or {})
        except ValidationError:
            logger.warning("chat_message_metadata_invalid")
            return cls()
