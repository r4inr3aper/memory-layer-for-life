"""Reading WhatsApp exports from Android and iOS, and cutting them into conversations."""

import io
import zipfile
from datetime import date, datetime

import pytest

from app.domain.errors import InvalidImportError
from app.domain.whatsapp import (
    MAX_UNIT_MESSAGES,
    ChatMessage,
    conversations,
    line_for,
    parse_export,
    read_export,
)

ANDROID = """12/10/24, 9:41 pm - Messages and calls are end-to-end encrypted. Tap to learn more.
12/10/24, 9:41 pm - Priya: Are we still on for Sunday?
12/10/24, 9:43 pm - Ada: Yes! Lunch at 1
and I'll bring the cake
12/10/24, 9:44 pm - Priya: <Media omitted>
13/10/24, 8:05 am - Ada: Raju owes me 500 for the tickets
"""

IOS = """\u200e[10/12/24, 9:41:05\u202fPM] Priya: Are we still on for Sunday?
[10/12/24, 9:43:10\u202fPM] Ada: Yes! Lunch at 1
[10/12/24, 9:44:00\u202fPM] Priya: \u200eimage omitted
[10/13/24, 12:05:00\u202fAM] Ada: Raju owes me 500
"""


def test_an_android_export_is_read_with_continued_lines_and_without_placeholders() -> None:
    chat = parse_export(ANDROID)

    assert [(m.sender, m.text) for m in chat.messages] == [
        ("Priya", "Are we still on for Sunday?"),
        ("Ada", "Yes! Lunch at 1\nand I'll bring the cake"),
        ("Ada", "Raju owes me 500 for the tickets"),
    ]
    assert chat.messages[0].sent_at == datetime(2024, 10, 12, 21, 41)
    assert chat.messages[2].sent_at == datetime(2024, 10, 13, 8, 5)
    assert chat.participants == (("Ada", 2), ("Priya", 1))
    assert chat.skipped == 2  # the encryption notice and the media


def test_an_ios_export_with_month_first_dates_and_invisible_marks_is_read() -> None:
    chat = parse_export(IOS)

    assert [m.text for m in chat.messages] == [
        "Are we still on for Sunday?",
        "Yes! Lunch at 1",
        "Raju owes me 500",
    ]
    # 10/13 can only be month first; midnight in 12-hour time is 00:05.
    assert chat.messages[2].sent_at == datetime(2024, 10, 13, 0, 5)


def test_ambiguous_dates_are_read_day_first() -> None:
    chat = parse_export("05/04/2025, 18:30 - Ada: Dentist next week\n")

    assert chat.messages[0].sent_at == datetime(2025, 4, 5, 18, 30)


@pytest.mark.parametrize(
    "text",
    ["", "just some notes\nwithout any dates", "12/10/24, 9:41 pm - Priya added you\n"],
)
def test_text_that_is_not_a_chat_is_refused(text: str) -> None:
    with pytest.raises(InvalidImportError):
        parse_export(text)


def test_the_chat_is_read_from_a_zip() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("_chat.txt", ANDROID.encode())
        archive.writestr("IMG-0001.jpg", b"\xff\xd8")

    assert read_export("WhatsApp Chat - Priya.zip", buffer.getvalue()) == ANDROID
    assert read_export("chat.txt", ANDROID.encode("utf-8-sig")) == ANDROID
    with pytest.raises(InvalidImportError):
        read_export("broken.zip", b"PK\x03\x04 not really")


def message(minute: int, sender: str = "Ada", hour: int = 10, day: int = 1) -> ChatMessage:
    return ChatMessage(sent_at=datetime(2026, 10, day, hour, minute), sender=sender, text="hi")


def test_conversations_break_on_long_gaps_and_size() -> None:
    messages = [message(0), message(10, "Priya"), message(50), message(55)]
    many = [message(minute % 60, hour=12 + minute // 60) for minute in range(MAX_UNIT_MESSAGES + 5)]

    assert [len(unit) for unit in conversations(messages, me="Ada")] == [2, 2]
    assert [len(unit) for unit in conversations(many, me="Ada")] == [MAX_UNIT_MESSAGES, 5]


def test_only_conversations_the_person_took_part_in_are_kept_by_default() -> None:
    messages = [message(0, "Priya"), message(5, "Raju"), message(0, "Priya", hour=15)]
    messages.append(message(3, "Ada", hour=15))

    mine = conversations(messages, me="Ada")
    everything = conversations(messages, me="Ada", only_mine=False)

    assert [[m.sender for m in unit] for unit in mine] == [["Priya", "Ada"]]
    assert len(everything) == 2


def test_older_messages_can_be_left_out() -> None:
    messages = [message(0, day=1), message(0, day=20)]

    [unit] = conversations(messages, me="Ada", since=date(2026, 10, 10))

    assert unit[0].sent_at.day == 20


def test_each_line_says_who_spoke() -> None:
    assert line_for(message(0, "Ada"), me="Ada") == "Me: hi"
    assert line_for(message(0, "Priya"), me="Ada") == "Priya: hi"
