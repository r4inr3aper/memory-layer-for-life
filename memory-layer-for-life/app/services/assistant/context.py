"""State shared by the tools of one assistant turn or scheduled run, and the events a
turn streams to the app."""

import enum
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.domain.principal import Principal
from app.models.chat_message import ChatMessage
from app.schemas.message_metadata import BrowserPreview, ConnectLink, ScheduleProposal


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolStarted:
    tool: str
    label: str


@dataclass(frozen=True, slots=True)
class BrowserUpdate:
    preview: BrowserPreview


@dataclass(frozen=True, slots=True)
class ConnectLinkShown:
    link: ConnectLink


@dataclass(frozen=True, slots=True)
class TurnStarted:
    user_message: ChatMessage


@dataclass(frozen=True, slots=True)
class TurnFinished:
    message: ChatMessage


@dataclass(frozen=True, slots=True)
class TurnFailed:
    error_code: str
    message: str


ProgressEvent = TextDelta | ToolStarted | BrowserUpdate | ConnectLinkShown
TurnEvent = TurnStarted | ProgressEvent | TurnFinished | TurnFailed
EventSink = Callable[[ProgressEvent], Awaitable[None]]


async def discard_event(event: ProgressEvent) -> None:
    """Sink for runs nobody watches, such as scheduled runs."""
    return None


class WritePolicy(enum.Enum):
    """Which app actions that change data the assistant may take.

    In chat the user confirms each one in conversation, as the instructions require. A
    scheduled run has nobody to ask, so it may change data only in the app it delivers
    to, and in none when it delivers to chat.
    """

    CONFIRM_IN_CHAT = "confirm_in_chat"
    DELIVERY_APP_ONLY = "delivery_app_only"


@dataclass
class TurnContext:
    principal: Principal
    timezone_name: str
    # The user's message that started the turn, kept on a schedule proposal.
    original_prompt: str
    emit: EventSink = discard_event
    allow_proposals: bool = True
    write_policy: WritePolicy = WritePolicy.CONFIRM_IN_CHAT
    # The app a scheduled run may change data in. None means no app.
    delivery_app: str | None = None
    # Outcomes the tools leave for the caller.
    browser_preview: BrowserPreview | None = None
    connect_link: ConnectLink | None = None
    proposal: ScheduleProposal | None = None
    # Successful app tool calls, as (app, tool slug).
    executed: list[tuple[str, str]] = field(default_factory=list)
    # Per-turn caches of Composio lookups.
    app_sessions: dict[str, str] = field(default_factory=dict)
    active_accounts: dict[str, list[str]] | None = None
