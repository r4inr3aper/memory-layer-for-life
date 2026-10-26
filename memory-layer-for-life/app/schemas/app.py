"""Request and response contracts of the assistant app: the user, threads, messages,
the reply stream, schedules, and app connections."""

import base64
import binascii
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Final, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import is_known_timezone
from app.domain.attachments import ATTACHMENT_TYPES
from app.domain.enums import (
    ChatRole,
    DevicePlatform,
    MemoryStatus,
    MemoryType,
    ScheduleDelivery,
    ScheduleFrequency,
    ScheduleRunStatus,
    ScheduleRunTrigger,
    ScheduleStatus,
    ThreadKind,
    ToolConnectionStatus,
    UsageGranularity,
    Weekday,
)
from app.schemas.common import ResponseSchema, StrictSchema
from app.schemas.message_metadata import BrowserPreview, ConnectLink, MessageMetadata

# --- User ------------------------------------------------------------------------------


_ICON: Final = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_COLOR: Final = re.compile(r"^#[0-9A-Fa-f]{6}$")


_CLOCK_TIME = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


def _clock_time(value: str) -> str:
    """``HH:MM`` in 24-hour form, as sent."""
    text = value.strip()
    if _CLOCK_TIME.fullmatch(text) is None:
        raise ValueError("must be HH:MM in 24-hour form")
    return text


class MeResponse(ResponseSchema):
    id: uuid.UUID
    email: str | None
    display_name: str | None
    assistant_name: str | None = Field(description="Null means the default, Cooper.")
    assistant_subtitle: str | None
    assistant_icon: str | None
    assistant_color: str | None
    notifications_enabled: bool
    memory_capture_enabled: bool = Field(description="Whether chats become memories.")
    timezone: str | None = Field(description="IANA timezone the app last reported.")
    brief_enabled: bool = Field(description="A daily brief in chat at `brief_time`.")
    brief_time: str = Field(description="HH:MM, local.")
    reminders_enabled: bool = Field(description="Push for reminders the user set.")
    quiet_hours_start: str | None = Field(description="HH:MM; no brief push from then.")
    quiet_hours_end: str | None = Field(description="HH:MM; may be earlier than the start.")
    created_at: datetime


class UpdateMeRequest(StrictSchema):
    """Change only the fields sent. A text field sent as null or "" returns to the default."""

    assistant_name: str | None = Field(default=None, max_length=40)
    assistant_subtitle: str | None = Field(default=None, max_length=60)
    assistant_icon: str | None = Field(default=None, description="An icon key, e.g. sparkles.")
    assistant_color: str | None = Field(default=None, description="#RRGGBB.")
    notifications_enabled: bool | None = None
    memory_capture_enabled: bool | None = None
    timezone: str | None = Field(default=None, description="An IANA timezone.")
    brief_enabled: bool | None = None
    brief_time: str | None = Field(default=None, description="HH:MM, 24-hour, local.")
    reminders_enabled: bool | None = None
    quiet_hours_start: str | None = Field(
        default=None, description="HH:MM. Send both quiet-hours fields, or both as null."
    )
    quiet_hours_end: str | None = Field(default=None, description="HH:MM.")

    @field_validator("assistant_name", "assistant_subtitle")
    @classmethod
    def blank_means_default(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("assistant_icon")
    @classmethod
    def icon_must_be_a_key(cls, value: str | None) -> str | None:
        if value and not _ICON.fullmatch(value):
            raise ValueError("assistant_icon must be letters, digits, - or _")
        return value or None

    @field_validator("assistant_color")
    @classmethod
    def color_must_be_hex(cls, value: str | None) -> str | None:
        if value and not _COLOR.fullmatch(value):
            raise ValueError("assistant_color must be #RRGGBB")
        return value or None

    @field_validator(
        "notifications_enabled", "memory_capture_enabled", "brief_enabled", "reminders_enabled"
    )
    @classmethod
    def notifications_cannot_be_null(cls, value: bool | None) -> bool | None:
        # Sent explicitly as null would mean "default", which a switch does not have.
        if value is None:
            raise ValueError("must be true or false")
        return value

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_known(cls, value: str | None) -> str | None:
        return _known_timezone(value)

    @field_validator("brief_time")
    @classmethod
    def brief_time_is_a_time(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("must be HH:MM")
        return _clock_time(value)

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def quiet_hours_are_times(cls, value: str | None) -> str | None:
        return _clock_time(value) if value is not None else None

    @model_validator(mode="after")
    def quiet_hours_go_together(self) -> "UpdateMeRequest":
        sent = {"quiet_hours_start", "quiet_hours_end"} & self.model_fields_set
        if sent and (
            len(sent) == 1 or (self.quiet_hours_start is None) != (self.quiet_hours_end is None)
        ):
            raise ValueError("send quiet_hours_start and quiet_hours_end together")
        return self


class UsageResponse(ResponseSchema):
    """Today's prompts. A prompt is a chat message sent or a scheduled run; the day is the
    UTC calendar day. Tokens and cost are today's model calls made for the user."""

    day: date = Field(description="The UTC day counted.")
    resets_at: datetime = Field(description="When the next day's prompts become available.")
    prompts_used: int
    prompt_limit: int | None = Field(description="Null when there is no limit.")
    prompts_remaining: int | None
    chat_messages: int
    scheduled_runs: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal | None
    currency: str = Field(description="ISO 4217 code of estimated_cost, e.g. INR.")
    estimated_cost: Decimal | None = Field(
        description="estimated_cost_usd in currency, at a fixed rate."
    )


class UsagePeriodResponse(ResponseSchema):
    start: date = Field(description="The period's first day (UTC).")
    prompts: int
    cost_usd: Decimal = Field(description="Estimated cost of the model calls made for the user.")
    cost: Decimal = Field(description="cost_usd in the history's currency.")
    input_tokens: int
    output_tokens: int


class UsageHistoryResponse(ResponseSchema):
    """Prompts and estimated model cost per period, for the usage chart. Periods are UTC;
    weeks start on Monday. The last period is the current one."""

    granularity: UsageGranularity
    currency: str = Field(description="ISO 4217 code of every cost, e.g. INR.")
    periods: list[UsagePeriodResponse] = Field(description="Oldest first, with empty ones.")
    total_cost_usd: Decimal
    total_cost: Decimal
    total_prompts: int


class AccountDeletionResponse(ResponseSchema):
    apps_disconnected: int
    apps_not_disconnected: int = Field(
        description="Connected apps Composio could not revoke; revoke them in each app."
    )
    identity_deleted: bool = Field(
        description="Whether the Supabase sign-in was deleted too. Signing in again starts "
        "a new, empty account either way."
    )


class RegisterPushTokenRequest(StrictSchema):
    token: str = Field(min_length=1, max_length=255, description="An Expo push token.")
    platform: DevicePlatform


class FeedbackRequest(StrictSchema):
    message: str = Field(min_length=1, max_length=4000)
    platform: DevicePlatform | None = None
    app_version: str | None = Field(default=None, max_length=40)

    @field_validator("message")
    @classmethod
    def message_must_have_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must contain text")
        return value


class FeedbackResponse(ResponseSchema):
    id: uuid.UUID
    created_at: datetime


# --- Threads and messages --------------------------------------------------------------


class ThreadResponse(ResponseSchema):
    id: uuid.UUID
    kind: ThreadKind
    title: str
    created_at: datetime
    updated_at: datetime = Field(description="Moves forward with every new message.")


class CreateThreadRequest(StrictSchema):
    """Creates a side thread. The main thread is created with ``POST /threads/main``."""

    title: str | None = Field(default=None, max_length=200)


class SavedMemoryResponse(ResponseSchema):
    """A memory a message is evidence for."""

    memory_id: uuid.UUID
    title: str
    memory_type: MemoryType
    status: MemoryStatus = Field(
        description="`active` when it was accepted (by the user or on its own), `proposed` "
        "while it waits in To review."
    )


class ChatMessageResponse(ResponseSchema):
    id: uuid.UUID
    thread_id: uuid.UUID
    role: ChatRole
    content: str
    metadata: MessageMetadata
    created_at: datetime
    updated_at: datetime
    saved_memories: list[SavedMemoryResponse] = Field(
        default_factory=list,
        description="For the user's messages in a listed page: what was remembered from "
        "them. Chats are read for memories a few minutes after they go quiet.",
    )


# Base64 of the largest file the API could be configured to accept, with headroom. The
# configured limit (CHAT_MAX_ATTACHMENT_BYTES) is checked on the decoded bytes.
_MAX_ATTACHMENT_BASE64_CHARS: Final = 30_000_000


class AttachmentInput(StrictSchema):
    name: str = Field(min_length=1, max_length=200)
    media_type: str = Field(
        description="image/jpeg, image/png, image/gif, image/webp, or application/pdf."
    )
    data: str = Field(max_length=_MAX_ATTACHMENT_BASE64_CHARS, description="Base64 content.")

    @field_validator("media_type")
    @classmethod
    def media_type_must_be_supported(cls, value: str) -> str:
        if value not in ATTACHMENT_TYPES:
            raise ValueError("only images and PDFs can be attached")
        return value

    @field_validator("data")
    @classmethod
    def data_must_be_base64(cls, value: str) -> str:
        try:
            base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("data is not valid base64") from error
        return value

    def decoded(self) -> bytes:
        return base64.b64decode(self.data)


class SendMessageRequest(StrictSchema):
    content: str = Field(default="", description="May be empty when files are attached.")
    attachments: list[AttachmentInput] = Field(default_factory=list)
    timezone: str = Field(
        default="UTC",
        description="IANA timezone of the user. Used for the time and for schedules.",
    )

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_known(cls, value: str) -> str:
        if not is_known_timezone(value):
            raise ValueError("timezone is not a known IANA timezone")
        return value

    @model_validator(mode="after")
    def needs_text_or_files(self) -> "SendMessageRequest":
        if not self.content.strip() and not self.attachments:
            raise ValueError("send text, files, or both")
        return self


# --- Reply stream ----------------------------------------------------------------------


class TurnStartedEvent(BaseModel):
    type: Literal["turn_started"] = "turn_started"
    user_message: ChatMessageResponse


class TextDeltaEvent(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolStartedEvent(BaseModel):
    type: Literal["tool_started"] = "tool_started"
    tool: str
    label: str


class BrowserEvent(BaseModel):
    type: Literal["browser"] = "browser"
    browser_preview: BrowserPreview


class ConnectLinkEvent(BaseModel):
    type: Literal["connect_link"] = "connect_link"
    connect_link: ConnectLink


class FinalEvent(BaseModel):
    type: Literal["final"] = "final"
    message: ChatMessageResponse


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    error_code: str
    message: str


TurnStreamEvent = Annotated[
    TurnStartedEvent
    | TextDeltaEvent
    | ToolStartedEvent
    | BrowserEvent
    | ConnectLinkEvent
    | FinalEvent
    | ErrorEvent,
    Field(discriminator="type"),
]


# --- Schedules -------------------------------------------------------------------------


class ScheduleResponse(ResponseSchema):
    id: uuid.UUID
    title: str
    original_prompt: str
    task: str
    frequency: ScheduleFrequency
    local_time: str = Field(description="HH:MM, 24-hour, in the schedule's timezone.")
    weekdays: list[Weekday] = Field(description="Weekly: the days it runs on, in order.")
    day_of_month: int | None = Field(
        description="Monthly: 1 to 31; a shorter month runs on its last day."
    )
    start_date: date | None = Field(
        description="Once: the day it runs. Interval: the day of its first run."
    )
    interval_hours: int | None = Field(description="Interval: hours between runs.")
    timezone: str
    delivery: ScheduleDelivery
    delivery_target: str | None
    status: ScheduleStatus
    next_run_at: datetime | None
    next_run_local: str | None = Field(
        description="The next run as YYYY-MM-DDTHH:MM in the schedule's timezone."
    )
    last_run_at: datetime | None
    last_run_status: ScheduleRunStatus | None
    last_run_summary: str | None
    last_run_error: str | None
    run_count: int
    source_thread_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


def _known_timezone(value: str | None) -> str | None:
    if value is not None and not is_known_timezone(value):
        raise ValueError("timezone is not a known IANA timezone")
    return value


class _ScheduleRuleOptions(StrictSchema):
    """Rule fields only some frequencies use (``app.domain.schedule_rules``)."""

    weekdays: list[Weekday] | None = Field(
        default=None, min_length=1, max_length=7, description="Weekly: the days it runs on."
    )
    day_of_month: int | None = Field(
        default=None, ge=1, le=31, description="Monthly. A shorter month runs on its last day."
    )
    start_date: date | None = Field(
        default=None,
        description="Once: the day it runs (required). Interval: the day of the first run "
        "(default: today).",
    )
    interval_hours: int | None = Field(
        default=None, ge=1, le=24, description="Interval: hours between runs."
    )


class CreateScheduleRequest(_ScheduleRuleOptions):
    title: str = Field(min_length=1, max_length=120)
    task: str = Field(min_length=1, max_length=2000, description="What to do on each run.")
    frequency: ScheduleFrequency
    local_time: str = Field(description="HH:MM, 24-hour, in the timezone below.")
    timezone: str
    delivery: ScheduleDelivery = ScheduleDelivery.CHAT
    delivery_target: str | None = Field(default=None, max_length=200)

    @field_validator("title", "task")
    @classmethod
    def must_have_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must contain text")
        return value.strip()

    @field_validator("delivery_target")
    @classmethod
    def blank_target_means_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_known(cls, value: str) -> str:
        _known_timezone(value)
        return value


_RULE_FIELDS = frozenset(
    {
        "frequency",
        "local_time",
        "weekdays",
        "day_of_month",
        "start_date",
        "interval_hours",
        "timezone",
    }
)


class UpdateScheduleRequest(_ScheduleRuleOptions):
    """Only the fields sent change. Changing the rule needs only the fields that differ;
    when the frequency changes, fields the new one does not use are dropped. A cancelled
    schedule cannot be changed."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    task: str | None = Field(default=None, min_length=1, max_length=2000)
    frequency: ScheduleFrequency | None = None
    local_time: str | None = Field(default=None, description="HH:MM, 24-hour.")
    timezone: str | None = Field(default=None, description="An IANA timezone.")
    delivery: ScheduleDelivery | None = None
    delivery_target: str | None = Field(default=None, max_length=200)
    status: ScheduleStatus | None = Field(
        default=None, description="Pause, resume, or cancel. Cancelling is final."
    )

    @field_validator("title", "task")
    @classmethod
    def must_have_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must contain text")
        return value.strip() if value is not None else None

    @field_validator("delivery_target")
    @classmethod
    def blank_target_means_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_known(cls, value: str | None) -> str | None:
        return _known_timezone(value)

    @model_validator(mode="after")
    def must_change_something(self) -> "UpdateScheduleRequest":
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        return self

    @property
    def changes_rule(self) -> bool:
        return bool(self.model_fields_set & _RULE_FIELDS)


class ScheduleRunResponse(ResponseSchema):
    id: uuid.UUID
    scheduled_task_id: uuid.UUID
    trigger: ScheduleRunTrigger
    status: ScheduleRunStatus
    scheduled_for: datetime | None
    started_at: datetime
    finished_at: datetime | None
    summary: str | None
    error_code: str | None
    error_message: str | None
    chat_message_id: uuid.UUID | None


class ActivityItemResponse(ResponseSchema):
    """A finished scheduled run, as the feed shows it."""

    run_id: uuid.UUID
    scheduled_task_id: uuid.UUID
    title: str
    trigger: ScheduleRunTrigger
    status: ScheduleRunStatus
    summary: str | None
    error_message: str | None
    delivery: ScheduleDelivery
    finished_at: datetime | None
    thread_id: uuid.UUID | None = Field(description="Where the result was posted, for chat.")
    chat_message_id: uuid.UUID | None


class ConfirmProposalResponse(ResponseSchema):
    message: ChatMessageResponse
    schedule: ScheduleResponse


# --- App connections -------------------------------------------------------------------


class ToolActionResponse(ResponseSchema):
    name: str
    description: str


class ToolResponse(ResponseSchema):
    slug: str
    name: str
    description: str
    category: str
    logo_url: str
    actions: list[ToolActionResponse]
    status: ToolConnectionStatus
    connected_label: str | None
    connected_email: str | None
    connected_at: datetime | None
    last_checked_at: datetime | None


class ConnectToolRequest(StrictSchema):
    callback_url: str | None = Field(
        default=None,
        max_length=2000,
        description="Where Composio sends the user after authorizing, such as an app link.",
    )

    @field_validator("callback_url")
    @classmethod
    def callback_must_be_an_absolute_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if not parts.scheme or parts.scheme.lower() in {"javascript", "data", "file", "vbscript"}:
            raise ValueError("callback_url must be an absolute app or web URL")
        return value


class ConnectToolResponse(ResponseSchema):
    tool: ToolResponse
    connect_url: str | None = Field(
        description="Open this to authorize the app. Absent when it was already connected."
    )
