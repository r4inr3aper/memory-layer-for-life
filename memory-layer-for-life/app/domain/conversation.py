"""Rules for chats with the assistant that need no database and no model (ADR-048).

* Admission: whether a line the user wrote can carry something to remember. Greetings,
  thanks, and approvals ("yes, send it") cannot on their own, but they still give the
  lines around them their meaning, so they travel with a captured segment as context.
  A line said again within a day (a resend) is dropped. Whether a request to the
  assistant ("can you find flights") holds a memory is the extractor's call, made with
  the assistant's reply in view: a word list cannot tell "find flights" from "find
  flights for my sister's wedding on the 12th".
* Segments: what the user said since the last capture, read once the chat goes quiet,
  in order, each line with the assistant message that came before it.
* Titles: a side chat is named from its first message at once, and later by the
  extractor from the conversation.
"""

import re
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from urllib.parse import urlparse

from app.domain.enums import ChatRole
from app.domain.memory_policy import clean_title

MIN_WORDS: Final = 3
# How much of the assistant message before a line travels with it as context.
ASSISTANT_CONTEXT_CHARS: Final = 600
CHAT_TITLE_MAX_CHARS: Final = 48

_ACK_TERMS: Final[frozenset[str]] = frozenset(
    {
        "ok",
        "okay",
        "thanks",
        "thank",
        "you",
        "thx",
        "ty",
        "cool",
        "great",
        "nice",
        "good",
        "got",
        "it",
        "done",
        "sure",
        "yep",
        "yup",
        "yes",
        "no",
        "alright",
        "perfect",
        "awesome",
        "a",
        "lot",
        "so",
        "much",
        "this",
        "is",
    }
)
_APPROVAL_PREFIXES: Final = (
    "yes",
    "yep",
    "yeah",
    "ok",
    "okay",
    "confirm",
    "approved",
    "proceed",
    "go ahead",
    "do it",
    "send it",
    "create it",
)
_APPROVAL_BLOCKERS: Final = ("?", " not ", " don't", " dont", " stop", " cancel")
_EDGE_PUNCTUATION: Final = ".,;:!?\"'()[]{}"

_URL: Final = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_FILLER: Final = re.compile(
    r"^(?:"
    r"(?:hey|hi|hello|yo|so|um|uh|ok|okay)\b[\s,!.]*"
    r"|(?:please|pls|plz|kindly)\b[\s,]*"
    r"|(?:can|could|would|will) you\b\s*(?:please\b\s*)?"
    r"|i (?:want|need) you to\b\s*"
    r")",
    re.IGNORECASE,
)


class Admission(StrEnum):
    # Says something that may be worth remembering; the extractor decides.
    CAPTURE = "capture"
    # Context only.
    TOO_SHORT = "too_short"
    ACKNOWLEDGEMENT = "acknowledgement"
    APPROVAL = "approval"
    # Said already within the window: dropped.
    REPEAT = "repeat"


def is_explicit_approval(text: str) -> bool:
    """True when a short user message clearly approves executing a pending action."""
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    if not cleaned or len(cleaned) > 80:
        return False
    framed = f" {cleaned} "
    if any(blocker in framed for blocker in _APPROVAL_BLOCKERS):
        return False
    return any(cleaned.startswith(prefix) for prefix in _APPROVAL_PREFIXES)


def repeat_key(text: str) -> str:
    """The form two lines must share to count as the same line said again."""
    return " ".join(text.lower().split()).strip(_EDGE_PUNCTUATION + " ")


def admission(text: str, *, said_recently: Collection[str] = ()) -> Admission:
    """Whether a line the user wrote can carry a memory. ``said_recently`` holds the
    ``repeat_key`` of lines already captured within the window."""
    words = text.split()
    if len(words) < MIN_WORDS:
        return Admission.TOO_SHORT
    tokens = [word.lower().strip(_EDGE_PUNCTUATION) for word in words]
    if all(token in _ACK_TERMS for token in tokens if token):
        return Admission.ACKNOWLEDGEMENT
    if is_explicit_approval(text) and len(words) <= 6:
        return Admission.APPROVAL
    if repeat_key(text) in said_recently:
        return Admission.REPEAT
    return Admission.CAPTURE


# --- Segments ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChatLine:
    """A stored chat message as the capture reads it. ``text`` is what the user typed;
    empty for a message that only carried files."""

    id: uuid.UUID
    role: ChatRole
    text: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CapturedLine:
    line: ChatLine
    # The assistant message just before it, shortened; context, never evidence.
    assistant_before: str | None
    admission: Admission


@dataclass(frozen=True, slots=True)
class SegmentPlan:
    # The user's lines to capture, in order. Repeats and file-only messages are left out.
    lines: tuple[CapturedLine, ...]
    # The new capture watermark: the time of the last message read. None: nothing read.
    through: datetime | None

    @property
    def worth_extracting(self) -> bool:
        """At least one line can carry a memory; otherwise no model call is spent."""
        return any(captured.admission is Admission.CAPTURE for captured in self.lines)


def plan_segment(
    lines: Sequence[ChatLine],
    *,
    previous_assistant: str | None,
    said_recently: Collection[str],
    max_user_lines: int,
) -> SegmentPlan:
    """Read a chat's messages since the last capture, oldest first, into one segment of at
    most ``max_user_lines`` user lines. Lines past that are left for the next segment."""
    assistant_before = _shorten(previous_assistant)
    seen = set(said_recently)
    captured: list[CapturedLine] = []
    through: datetime | None = None
    for line in lines:
        if line.role is ChatRole.ASSISTANT:
            assistant_before = _shorten(line.text)
            through = line.created_at
            continue
        if len(captured) >= max_user_lines:
            break
        through = line.created_at
        text = line.text.strip()
        if not text:
            continue
        decision = admission(text, said_recently=seen)
        seen.add(repeat_key(text))
        if decision is Admission.REPEAT:
            continue
        captured.append(CapturedLine(line, assistant_before, decision))
    return SegmentPlan(tuple(captured), through)


def _shorten(text: str | None) -> str | None:
    if text is None or not text.strip():
        return None
    line = " ".join(text.split())
    if len(line) <= ASSISTANT_CONTEXT_CHARS:
        return line
    return line[: ASSISTANT_CONTEXT_CHARS - 1] + "…"


# --- Titles ------------------------------------------------------------------------


def heuristic_title(text: str) -> str:
    """A side chat's name from its first message, until the extractor names it: links
    become what they are ("LinkedIn post"), polite openings go. Empty when nothing is
    left."""
    labels: list[str] = []

    def label_link(match: re.Match[str]) -> str:
        labels.append(_link_label(match.group(0)))
        return " "

    body = " ".join(_URL.sub(label_link, text).split())
    while (stripped := _FILLER.sub("", body, count=1)) != body:
        body = stripped
    body = body.strip(_EDGE_PUNCTUATION + " -")
    if not body:
        body = labels[0] if labels else ""
    elif labels and len(body.split()) <= 3:
        body = f"{body} ({labels[0]})"
    return clean_title(body, max_chars=CHAT_TITLE_MAX_CHARS) if body else ""


def conversation_title(text: str | None) -> str | None:
    """The extractor's name for a conversation, cleaned; None when it gave none."""
    if text is None:
        return None
    title = clean_title(text, max_chars=CHAT_TITLE_MAX_CHARS)
    return title or None


def _link_label(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if "linkedin" in host or host == "lnkd.in":
        return "LinkedIn post"
    if "youtube" in host or host == "youtu.be":
        return "YouTube video"
    if "github" in host:
        return "GitHub link"
    return f"{host} link" if host else "Link"
