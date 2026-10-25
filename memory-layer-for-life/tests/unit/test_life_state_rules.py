"""What is open, when the brief goes, and what it says: the rules of life state."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.domain.enums import LifeBucket
from app.domain.life_state import (
    BRIEF_GRACE,
    NOTHING_DUE,
    BriefInputs,
    BriefItem,
    BriefReminder,
    brief_due,
    bucket_for,
    compose_brief,
    in_quiet_hours,
    is_stale,
)

TODAY = date(2026, 10, 24)
KOLKATA = ZoneInfo("Asia/Kolkata")


def item(content: str, due_on: date | None = None) -> BriefItem:
    return BriefItem(memory_id=uuid.uuid4(), content=content, due_on=due_on)


# --- Buckets and staleness -------------------------------------------------------------


@pytest.mark.parametrize(
    ("due_on", "bucket"),
    [
        (None, LifeBucket.SOMEDAY),
        (TODAY - timedelta(days=1), LifeBucket.OVERDUE),
        (TODAY, LifeBucket.TODAY),
        (TODAY + timedelta(days=1), LifeBucket.UPCOMING),
        (TODAY + timedelta(days=7), LifeBucket.UPCOMING),
        (TODAY + timedelta(days=8), LifeBucket.LATER),
    ],
)
def test_items_fall_into_buckets_by_due_date(due_on: date | None, bucket: LifeBucket) -> None:
    assert bucket_for(due_on, TODAY) is bucket


def test_an_item_untouched_for_two_weeks_is_stale_unless_it_is_due_later() -> None:
    now = datetime(2026, 10, 24, 9, tzinfo=UTC)
    old = now - timedelta(days=15)
    recent = now - timedelta(days=3)

    assert is_stale(due_on=None, last_activity=old, now=now, today=TODAY)
    assert is_stale(due_on=TODAY - timedelta(days=30), last_activity=old, now=now, today=TODAY)
    assert not is_stale(due_on=TODAY + timedelta(days=30), last_activity=old, now=now, today=TODAY)
    assert not is_stale(due_on=None, last_activity=recent, now=now, today=TODAY)


# --- Quiet hours and the brief's slot --------------------------------------------------


@pytest.mark.parametrize(
    ("local", "start", "end", "quiet"),
    [
        (time(23, 0), time(22, 0), time(7, 0), True),
        (time(6, 59), time(22, 0), time(7, 0), True),
        (time(7, 0), time(22, 0), time(7, 0), False),
        (time(12, 0), time(22, 0), time(7, 0), False),
        (time(13, 30), time(13, 0), time(14, 0), True),
        (time(14, 0), time(13, 0), time(14, 0), False),
        (time(3, 0), None, None, False),
        (time(3, 0), time(8, 0), time(8, 0), False),
    ],
)
def test_quiet_hours_may_wrap_past_midnight(
    local: time, start: time | None, end: time | None, quiet: bool
) -> None:
    assert in_quiet_hours(local, start, end) is quiet


def test_the_brief_goes_once_a_day_after_its_time_and_not_hours_late() -> None:
    at = time(8, 0)
    before = datetime(2026, 10, 24, 7, 59, tzinfo=KOLKATA)
    on_time = datetime(2026, 10, 24, 8, 0, tzinfo=KOLKATA)
    late = datetime(2026, 10, 24, 8, 0, tzinfo=KOLKATA) + BRIEF_GRACE - timedelta(minutes=1)
    too_late = datetime(2026, 10, 24, 8, 0, tzinfo=KOLKATA) + BRIEF_GRACE

    assert not brief_due(before, at, None)
    assert brief_due(on_time, at, None)
    assert brief_due(late, at, date(2026, 10, 23))
    assert not brief_due(too_late, at, None)
    assert not brief_due(on_time, at, date(2026, 10, 24))


# --- Composing the brief ---------------------------------------------------------------


def test_the_brief_lists_each_kind_of_item_under_its_heading() -> None:
    follow_up = item("Send the invoice", TODAY - timedelta(days=1))
    brief = compose_brief(
        BriefInputs(
            today=TODAY,
            user_name="Ada",
            due_today=[item("Pay the electricity bill", TODAY)],
            overdue=[item("Renew passport", date(2026, 10, 20))],
            follow_ups=[follow_up],
            upcoming=[item("Dentist", date(2026, 10, 27))],
            stale=[item("Learn guitar")],
            reminders=[BriefReminder(memory_id=uuid.uuid4(), content="Call Mum", at=time(18, 0))],
            review_count=3,
        )
    )

    assert brief.text.startswith("Good morning, Ada. Here's Saturday, 24 October.")
    for heading, line in [
        ("**Due today**", "- Pay the electricity bill"),
        ("**Overdue**", "- Renew passport (due Tue 20 Oct)"),
        ("**Did these get done?**", "- Send the invoice"),
        ("**Coming up this week**", "- Dentist (Tue 27 Oct)"),
        ("**Reminders today**", "- 18:00 Call Mum"),
        ("**Still on?**", "- Learn guitar"),
    ]:
        assert f"{heading}\n{line}" in brief.text
    assert brief.text.endswith("3 new memories to review in Memories.")
    assert brief.summary == "1 due today · 1 overdue · 1 to check off"
    assert brief.follow_ups == (follow_up,)
    assert not brief.nothing_to_say


def test_a_quiet_day_says_so_and_has_nothing_to_send() -> None:
    brief = compose_brief(BriefInputs(today=TODAY, user_name=None))

    assert brief.text.startswith("Good morning. Here's Saturday")
    assert "Nothing is due today. Enjoy your day." in brief.text
    assert brief.summary == NOTHING_DUE
    assert brief.nothing_to_say


def test_memories_to_review_alone_are_worth_a_brief() -> None:
    brief = compose_brief(BriefInputs(today=TODAY, user_name=None, review_count=1))

    assert not brief.nothing_to_say
    assert "1 new memory to review in Memories." in brief.text


def test_long_lists_are_cut() -> None:
    brief = compose_brief(
        BriefInputs(
            today=TODAY, user_name=None, due_today=[item(f"Task {n}", TODAY) for n in range(9)]
        )
    )

    assert "- Task 4" in brief.text
    assert "- Task 5" not in brief.text
    assert brief.summary == "9 due today"
