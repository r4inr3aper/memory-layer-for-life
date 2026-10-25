from datetime import UTC, date, datetime, time

import pytest

from app.domain.enums import ScheduleFrequency, Weekday
from app.domain.errors import InvalidScheduleError
from app.domain.schedule_rules import (
    RuleFields,
    ScheduleRule,
    parse_local_date,
    parse_local_time,
    weekday_number,
)

WEEKDAYS = (
    Weekday.MONDAY,
    Weekday.TUESDAY,
    Weekday.WEDNESDAY,
    Weekday.THURSDAY,
    Weekday.FRIDAY,
)


def daily(at: time, zone: str = "UTC") -> ScheduleRule:
    return ScheduleRule(frequency=ScheduleFrequency.DAILY, local_time=at, timezone_name=zone)


def weekly(*days: Weekday, at: time = time(9, 0), zone: str = "UTC") -> ScheduleRule:
    return ScheduleRule(
        frequency=ScheduleFrequency.WEEKLY, local_time=at, timezone_name=zone, weekdays=days
    )


def monthly(day: int, at: time = time(9, 0), zone: str = "UTC") -> ScheduleRule:
    return ScheduleRule(
        frequency=ScheduleFrequency.MONTHLY, local_time=at, timezone_name=zone, day_of_month=day
    )


def once(on: date, at: time = time(9, 0), zone: str = "UTC") -> ScheduleRule:
    return ScheduleRule(
        frequency=ScheduleFrequency.ONCE, local_time=at, timezone_name=zone, start_date=on
    )


def every(hours: int, start: date, at: time, zone: str = "UTC") -> ScheduleRule:
    return ScheduleRule(
        frequency=ScheduleFrequency.INTERVAL,
        local_time=at,
        timezone_name=zone,
        start_date=start,
        interval_hours=hours,
    )


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# --- Daily -----------------------------------------------------------------------------


def test_daily_fires_later_today_when_the_time_is_still_ahead() -> None:
    assert daily(time(8, 0)).next_after(utc(2026, 10, 18, 6, 0)) == utc(2026, 10, 18, 8, 0)


def test_daily_moves_to_tomorrow_once_the_time_has_passed() -> None:
    assert daily(time(8, 0)).next_after(utc(2026, 10, 18, 9, 0)) == utc(2026, 10, 19, 8, 0)


def test_the_next_slot_is_strictly_after_the_given_instant() -> None:
    assert daily(time(8, 0)).next_after(utc(2026, 10, 18, 8, 0)) == utc(2026, 10, 19, 8, 0)


def test_times_are_read_in_the_schedule_timezone() -> None:
    # 08:00 in Kolkata (UTC+05:30) is 02:30 UTC.
    rule = daily(time(8, 0), "Asia/Kolkata")

    assert rule.next_after(utc(2026, 10, 18, 0, 0)) == utc(2026, 10, 18, 2, 30)


def test_a_schedule_keeps_its_local_time_across_a_daylight_saving_change() -> None:
    # New York leaves daylight saving time on 2026-11-01: 08:00 is 12:00 UTC before
    # and 13:00 UTC after.
    rule = daily(time(8, 0), "America/New_York")

    before = rule.next_after(utc(2026, 10, 31, 0, 0))
    assert before is not None
    after = rule.next_after(before)

    assert before == utc(2026, 10, 31, 12, 0)
    assert after == utc(2026, 11, 1, 13, 0)


def test_a_time_in_the_spring_forward_gap_fires_an_hour_later_on_the_clock() -> None:
    # On 2026-03-08 New York clocks jump from 02:00 to 03:00, so 02:30 does not exist.
    rule = daily(time(2, 30), "America/New_York")

    assert rule.next_after(utc(2026, 3, 8, 0, 0)) == utc(2026, 3, 8, 7, 30)  # 03:30 EDT


def test_a_repeated_time_fires_at_its_first_occurrence() -> None:
    # On 2026-11-01 New York shows 01:30 twice; the first is 05:30 UTC.
    rule = daily(time(1, 30), "America/New_York")

    assert rule.next_after(utc(2026, 11, 1, 0, 0)) == utc(2026, 11, 1, 5, 30)


# --- Weekly ----------------------------------------------------------------------------


def test_weekly_finds_the_named_weekday() -> None:
    # 2026-10-18 is a Sunday.
    rule = weekly(Weekday.WEDNESDAY, at=time(9, 30))

    assert rule.next_after(utc(2026, 10, 18, 12, 0)) == utc(2026, 10, 21, 9, 30)


def test_weekly_waits_a_full_week_when_today_s_slot_has_passed() -> None:
    rule = weekly(Weekday.SUNDAY)

    assert rule.next_after(utc(2026, 10, 18, 10, 0)) == utc(2026, 10, 25, 9, 0)


def test_weekdays_skip_the_weekend() -> None:
    rule = weekly(*WEEKDAYS)
    friday_evening = utc(2026, 10, 23, 18, 0)

    assert rule.next_after(friday_evening) == utc(2026, 10, 26, 9, 0)  # Monday


def test_several_days_run_on_each_of_them_in_order() -> None:
    rule = weekly(Weekday.FRIDAY, Weekday.TUESDAY)
    slots = []
    instant = utc(2026, 10, 18, 0, 0)  # Sunday
    for _ in range(4):
        upcoming = rule.next_after(instant)
        assert upcoming is not None
        slots.append(upcoming)
        instant = upcoming

    assert [slot.date() for slot in slots] == [
        date(2026, 10, 20),
        date(2026, 10, 23),
        date(2026, 10, 27),
        date(2026, 10, 30),
    ]


def test_weekdays_are_kept_in_order_without_repeats() -> None:
    rule = weekly(Weekday.FRIDAY, Weekday.MONDAY, Weekday.FRIDAY)

    assert rule.weekdays == (Weekday.MONDAY, Weekday.FRIDAY)


# --- Monthly ---------------------------------------------------------------------------


def test_monthly_runs_on_its_day() -> None:
    assert monthly(15).next_after(utc(2026, 10, 18, 0, 0)) == utc(2026, 11, 15, 9, 0)


@pytest.mark.parametrize(
    ("after", "expected"),
    [
        (utc(2026, 4, 1, 0, 0), utc(2026, 4, 30, 9, 0)),  # April has 30 days
        (utc(2026, 2, 1, 0, 0), utc(2026, 2, 28, 9, 0)),
        (utc(2028, 2, 1, 0, 0), utc(2028, 2, 29, 9, 0)),  # a leap year
        (utc(2026, 5, 1, 0, 0), utc(2026, 5, 31, 9, 0)),
    ],
)
def test_the_31st_runs_on_the_last_day_of_a_shorter_month(
    after: datetime, expected: datetime
) -> None:
    assert monthly(31).next_after(after) == expected


def test_a_monthly_rule_looks_into_the_next_month_after_its_day() -> None:
    assert monthly(31).next_after(utc(2026, 4, 30, 10, 0)) == utc(2026, 5, 31, 9, 0)


# --- Once ------------------------------------------------------------------------------


def test_once_fires_on_its_date_in_its_timezone() -> None:
    rule = once(date(2026, 10, 25), at=time(9, 0), zone="Asia/Kolkata")

    assert rule.next_after(utc(2026, 10, 24, 0, 0)) == utc(2026, 10, 25, 3, 30)


def test_once_never_fires_again_after_its_moment() -> None:
    rule = once(date(2026, 10, 25))

    assert rule.next_after(utc(2026, 10, 25, 9, 0)) is None
    assert rule.next_after(utc(2026, 11, 1, 0, 0)) is None


# --- Interval --------------------------------------------------------------------------


def test_an_interval_starts_at_its_first_run() -> None:
    rule = every(3, date(2026, 10, 24), time(9, 0))

    assert rule.next_after(utc(2026, 10, 24, 6, 0)) == utc(2026, 10, 24, 9, 0)


def test_an_interval_continues_its_series_strictly_after_an_instant() -> None:
    rule = every(3, date(2026, 10, 24), time(9, 0))

    assert rule.next_after(utc(2026, 10, 24, 9, 0)) == utc(2026, 10, 24, 12, 0)
    assert rule.next_after(utc(2026, 10, 24, 13, 0)) == utc(2026, 10, 24, 15, 0)
    # Days later, the series is still on its three-hour grid from 09:00.
    assert rule.next_after(utc(2026, 10, 27, 10, 0)) == utc(2026, 10, 27, 12, 0)


def test_an_interval_is_elapsed_time_across_a_daylight_saving_change() -> None:
    # New York falls back at 02:00 EDT on 2026-11-01 (06:00 UTC). Every 3 hours from
    # midnight EDT stays 3 hours apart in real time; the clock then shows 02:00 EST.
    rule = every(3, date(2026, 11, 1), time(0, 0), "America/New_York")
    first = rule.next_after(utc(2026, 11, 1, 0, 0))
    assert first is not None
    second = rule.next_after(first)

    assert first == utc(2026, 11, 1, 4, 0)
    assert second == utc(2026, 11, 1, 7, 0)
    assert rule.interval is not None and second - first == rule.interval


def test_an_interval_without_a_date_starts_today_in_its_timezone() -> None:
    fields = RuleFields(
        frequency=ScheduleFrequency.INTERVAL,
        local_time=time(9, 0),
        timezone="Asia/Kolkata",
        interval_hours=6,
    )

    # 2026-10-24 20:00 UTC is already 25 October in Kolkata.
    rule = fields.build(utc(2026, 10, 24, 20, 0))

    assert rule.start_date == date(2026, 10, 25)


def test_building_keeps_an_explicit_start_date() -> None:
    fields = RuleFields(
        frequency=ScheduleFrequency.ONCE,
        local_time=time(9, 0),
        timezone="UTC",
        start_date=date(2026, 12, 1),
    )

    assert fields.build(utc(2026, 10, 24, 0, 0)).start_date == date(2026, 12, 1)


# --- What a rule may contain -----------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"frequency": ScheduleFrequency.WEEKLY},
        {"frequency": ScheduleFrequency.DAILY, "weekdays": (Weekday.MONDAY,)},
        {"frequency": ScheduleFrequency.MONTHLY},
        {"frequency": ScheduleFrequency.DAILY, "day_of_month": 3},
        {"frequency": ScheduleFrequency.MONTHLY, "day_of_month": 32},
        {"frequency": ScheduleFrequency.MONTHLY, "day_of_month": 0},
        {"frequency": ScheduleFrequency.ONCE},
        {"frequency": ScheduleFrequency.DAILY, "start_date": date(2026, 1, 1)},
        {"frequency": ScheduleFrequency.INTERVAL, "start_date": date(2026, 1, 1)},
        {"frequency": ScheduleFrequency.DAILY, "interval_hours": 2},
        {
            "frequency": ScheduleFrequency.INTERVAL,
            "start_date": date(2026, 1, 1),
            "interval_hours": 0,
        },
        {
            "frequency": ScheduleFrequency.INTERVAL,
            "start_date": date(2026, 1, 1),
            "interval_hours": 25,
        },
    ],
    ids=lambda fields: "-".join(f"{key}={value}" for key, value in fields.items()),
)
def test_each_frequency_has_exactly_its_own_fields(fields: dict[str, object]) -> None:
    with pytest.raises(InvalidScheduleError):
        ScheduleRule(local_time=time(8, 0), timezone_name="UTC", **fields)  # type: ignore[arg-type]


def test_an_unknown_timezone_is_rejected() -> None:
    with pytest.raises(InvalidScheduleError, match="Unknown timezone"):
        daily(time(8, 0), "Mars/Olympus_Mons")


def test_a_naive_instant_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        daily(time(8, 0)).next_after(datetime(2026, 10, 18, 8, 0))


@pytest.mark.parametrize(("text", "expected"), [("08:00", time(8, 0)), (" 23:59 ", time(23, 59))])
def test_times_are_hh_mm(text: str, expected: time) -> None:
    assert parse_local_time(text) == expected


@pytest.mark.parametrize("text", ["8:00", "24:00", "12:60", "noon"])
def test_other_times_are_rejected(text: str) -> None:
    with pytest.raises(InvalidScheduleError):
        parse_local_time(text)


def test_dates_are_yyyy_mm_dd() -> None:
    assert parse_local_date("2026-10-25") == date(2026, 10, 25)


@pytest.mark.parametrize("text", ["2026-02-30", "25/10/2026", "tomorrow"])
def test_other_dates_are_rejected(text: str) -> None:
    with pytest.raises(InvalidScheduleError):
        parse_local_date(text)


def test_weekday_numbers_follow_datetime() -> None:
    assert [weekday_number(day) for day in Weekday] == list(range(7))
