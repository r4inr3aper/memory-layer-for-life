"""Reading a WhatsApp chat export and cutting it into units for the memory pipeline. No
database, no network.

An export is a text file (alone, or as ``_chat.txt`` in a zip) with one line per message:

* Android: ``12/10/24, 9:41 pm - Priya: See you at 6``
* iOS: ``[12/10/24, 9:41:05 PM] Priya: See you at 6``

A line without that prefix continues the message above it. Lines without a sender
("Messages and calls are end-to-end encrypted", "Priya added you") and media placeholders
("<Media omitted>", "image omitted") are skipped. Day and month order is inferred from
the dates themselves (a first number above 12 means day first); when every date is
ambiguous, day first is assumed, as in most of the world.

Units are conversations: consecutive messages less than ``CONVERSATION_GAP`` apart, at
most ``MAX_UNIT_MESSAGES`` each. Each message is written ``Me: ...`` or ``Priya: ...`` so
the extractor knows who said what; memories are about the person importing.
"""

import io
import re
import zipfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final

from app.domain.errors import InvalidImportError

CONVERSATION_GAP: Final = timedelta(minutes=30)
MAX_UNIT_MESSAGES: Final = 20
MAX_MESSAGE_CHARS: Final = 4000
# A zip may not expand beyond this, whatever it claims.
MAX_EXPANDED_BYTES: Final = 30 * 1024 * 1024
ME: Final = "Me"

_INVISIBLE: Final = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_SPACES: Final = re.compile("[\u00a0\u202f\u2007]")
_STAMP: Final = (
    r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4}),?\s+(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?"
    r"\s*([AaPp]\.?\s?[Mm]\.?)?"
)
_ANDROID: Final = re.compile(rf"^{_STAMP}\s+-\s+(.*)$")
_IOS: Final = re.compile(rf"^\[{_STAMP}\]\s+(.*)$")
_PLACEHOLDERS: Final = (
    "<media omitted>",
    "image omitted",
    "video omitted",
    "audio omitted",
    "sticker omitted",
    "gif omitted",
    "document omitted",
    "contact card omitted",
    "this message was deleted",
    "you deleted this message",
    "missed voice call",
    "missed video call",
    "<attached:",
    "null",
)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    sent_at: datetime  # local wall time of the exporting phone, no timezone
    sender: str
    text: str


@dataclass(frozen=True, slots=True)
class ParsedChat:
    messages: tuple[ChatMessage, ...]
    # Senders by how many messages they wrote, most first.
    participants: tuple[tuple[str, int], ...]
    skipped: int


@dataclass(frozen=True, slots=True)
class _Raw:
    numbers: tuple[int, int, int, int, int]
    meridiem: str | None
    rest: str


def read_export(file_name: str, data: bytes) -> str:
    """The export's text, from a ``.txt`` or a ``.zip`` holding one."""
    if file_name.lower().endswith(".zip") or data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                texts = [
                    info for info in archive.infolist() if info.filename.lower().endswith(".txt")
                ]
                if not texts:
                    raise InvalidImportError("The zip has no chat text file in it.")
                chosen = next(
                    (info for info in texts if info.filename.lower().endswith("_chat.txt")),
                    texts[0],
                )
                if chosen.file_size > MAX_EXPANDED_BYTES:
                    raise InvalidImportError("The chat in this zip is too large to import.")
                data = archive.read(chosen)
        except zipfile.BadZipFile as error:
            raise InvalidImportError("The file is not a valid zip.") from error
    return data.decode("utf-8-sig", errors="replace")


def _clean(line: str) -> str:
    return _SPACES.sub(" ", _INVISIBLE.sub("", line)).rstrip("\r")


def _match(line: str) -> _Raw | None:
    found = _IOS.match(line) or _ANDROID.match(line)
    if found is None:
        return None
    first, second, year, hour, minute = (int(found.group(index)) for index in range(1, 6))
    return _Raw(
        numbers=(first, second, year, hour, minute),
        meridiem=found.group(7),
        rest=found.group(8),
    )


def _day_first(stamps: Sequence[_Raw]) -> bool:
    if any(stamp.numbers[0] > 12 for stamp in stamps):
        return True
    return not any(stamp.numbers[1] > 12 for stamp in stamps)


def _when(stamp: _Raw, day_first: bool) -> datetime | None:
    first, second, year, hour, minute = stamp.numbers
    day, month = (first, second) if day_first else (second, first)
    if year < 100:
        year += 2000
    if stamp.meridiem is not None:
        pm = stamp.meridiem.lower().startswith("p")
        if hour == 12:
            hour = 12 if pm else 0
        elif pm:
            hour += 12
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def _skippable(text: str) -> bool:
    lowered = text.strip().lower()
    return not lowered or any(lowered.startswith(marker) for marker in _PLACEHOLDERS)


def parse_export(text: str) -> ParsedChat:
    """Every message of an export, oldest first. Raises ``InvalidImportError`` when the
    text does not look like a WhatsApp export."""
    entries: list[tuple[_Raw, list[str]]] = []
    for line in (_clean(line) for line in text.splitlines()):
        stamp = _match(line)
        if stamp is not None:
            entries.append((stamp, []))
        elif entries:
            entries[-1][1].append(line)
    if not entries:
        raise InvalidImportError(
            "This doesn't look like a WhatsApp chat export. In WhatsApp, open the chat, "
            "tap More > Export chat > Without media, and import that file."
        )
    day_first = _day_first([stamp for stamp, _ in entries])
    messages: list[ChatMessage] = []
    skipped = 0
    for stamp, continuation in entries:
        sender, separator, first_line = stamp.rest.partition(": ")
        sent_at = _when(stamp, day_first)
        body = "\n".join([first_line, *continuation]).strip()
        if not separator or sent_at is None or _skippable(body):
            skipped += 1
            continue
        messages.append(
            ChatMessage(sent_at=sent_at, sender=sender.strip(), text=body[:MAX_MESSAGE_CHARS])
        )
    if not messages:
        raise InvalidImportError("The chat has no messages to import.")
    counts = Counter(message.sender for message in messages)
    return ParsedChat(
        messages=tuple(messages),
        participants=tuple(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))),
        skipped=skipped,
    )


def conversations(
    messages: Sequence[ChatMessage],
    *,
    me: str,
    since: date | None = None,
    only_mine: bool = True,
) -> list[list[ChatMessage]]:
    """The chat cut into conversations, oldest first. ``only_mine`` keeps those the
    person took part in; ``since`` drops what came before that day."""
    units: list[list[ChatMessage]] = []
    for message in messages:
        if since is not None and message.sent_at.date() < since:
            continue
        current = units[-1] if units else None
        if (
            current is None
            or len(current) >= MAX_UNIT_MESSAGES
            or message.sent_at - current[-1].sent_at > CONVERSATION_GAP
        ):
            units.append([message])
        else:
            current.append(message)
    if only_mine:
        units = [unit for unit in units if any(message.sender == me for message in unit)]
    return units


def line_for(message: ChatMessage, *, me: str) -> str:
    """A message as the extractor reads it: who said it, then what."""
    speaker = ME if message.sender == me else message.sender
    return f"{speaker}: {message.text}"
