"""When the next daily brief is due, in the user's own timezone."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.domain.life_state import next_brief_at

KOLKATA = ZoneInfo("Asia/Kolkata")
BRIEF = time(8, 0)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=KOLKATA)


def test_before_the_brief_time_it_is_today_s() -> None:
    assert next_brief_at(at(1, 6), BRIEF, None) == at(1, 8)


def test_inside_the_window_and_not_sent_it_is_due_now() -> None:
    assert next_brief_at(at(1, 9), BRIEF, date(2026, 9, 30)) == at(1, 9)


def test_once_sent_today_it_is_tomorrow_s() -> None:
    assert next_brief_at(at(1, 9), BRIEF, date(2026, 10, 1)) == at(2, 8)


def test_after_the_window_it_is_tomorrow_s() -> None:
    assert next_brief_at(at(1, 12), BRIEF, None) == at(2, 8)


def test_a_brief_time_moved_later_after_today_s_brief_waits_for_tomorrow() -> None:
    assert next_brief_at(at(1, 9), time(20, 0), date(2026, 10, 1)) == at(2, 20)
