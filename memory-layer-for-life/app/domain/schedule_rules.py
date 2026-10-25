"""Schedule rules and the instants they fire at.

A rule is a wall-clock time in an IANA timezone, with a frequency:

* once, on one date;
* daily;
* weekly, on one or more weekdays (Monday to Friday is "weekdays");
* monthly, on a day of the month, or on the month's last day when the month is shorter,
  so the 31st runs on 30 April and on 28 or 29 February;
* every so many hours (interval), from a first run on a start date.

Instants are computed in the zone and stored in UTC, so a schedule keeps its local time
across daylight-saving changes. An interval is elapsed time instead: every 3 hours stays
3 hours across a change, so its wall-clock times shift by the change's hour.

Two local times need a rule of their own. A time that does not exist on a given day,
because it falls in the spring-forward gap, fires at the instant the clock shows one hour
later. A time that occurs twice, in the fall-back overlap, fires at its first occurrence.
Both follow from ``fold=0``, Python's default.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.enums import ScheduleFrequency, Weekday
from app.domain.errors import InvalidScheduleError

_LOCAL_TIME: Final = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_LOCAL_DATE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A monthly rule fires within two months of any instant; every other day-based rule
# fires within a week.
_SEARCH_DAYS: Final = 62

MIN_INTERVAL_HOURS: Final = 1
MAX_INTERVAL_HOURS: Final = 24

# Frequencies that start on a given date.
DATED_FREQUENCIES: Final = frozenset({ScheduleFrequency.ONCE, ScheduleFrequency.INTERVAL})


def weekday_number(weekday: Weekday) -> int:
    """Monday is 0, as in ``date.weekday()``."""
    return list(Weekday).index(weekday)


def parse_local_time(value: str) -> time:
    """Parse ``HH:MM`` in 24-hour form."""
    match = _LOCAL_TIME.fullmatch(value.strip())
    if match is None:
        raise InvalidScheduleError("A schedule time must be HH:MM in 24-hour form.")
    return time(int(match.group(1)), int(match.group(2)))


def parse_local_date(value: str) -> date:
    """Parse ``YYYY-MM-DD``."""
    text = value.strip()
    if _LOCAL_DATE.fullmatch(text) is None:
        raise InvalidScheduleError("A schedule date must be YYYY-MM-DD.")
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise InvalidScheduleError("A schedule date must be a real calendar date.") from error


def load_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise InvalidScheduleError(f"Unknown timezone: {name}") from error


@dataclass(frozen=True, slots=True)
class ScheduleRule:
    frequency: ScheduleFrequency
    local_time: time
    timezone_name: str
    # Weekly only. Kept in weekday order without repeats.
    weekdays: tuple[Weekday, ...] = ()
    # Monthly only, 1 to 31.
    day_of_month: int | None = None
    # Once: the day it runs. Interval: the day of the first run.
    start_date: date | None = None
    # Interval only.
    interval_hours: int | None = None

    def __post_init__(self) -> None:
        if self.local_time.tzinfo is not None:
            raise InvalidScheduleError("A schedule time is a wall-clock time without a zone.")
        if self.local_time.second or self.local_time.microsecond:
            raise InvalidScheduleError("A schedule time has minute precision.")
        object.__setattr__(self, "weekdays", tuple(sorted(set(self.weekdays), key=weekday_number)))
        frequency = self.frequency
        if (frequency is ScheduleFrequency.WEEKLY) != bool(self.weekdays):
            raise InvalidScheduleError(
                "A weekly schedule runs on at least one weekday; other schedules name none."
            )
        if (frequency is ScheduleFrequency.MONTHLY) != (self.day_of_month is not None):
            raise InvalidScheduleError(
                "A monthly schedule names a day of the month; other schedules do not."
            )
        if self.day_of_month is not None and not 1 <= self.day_of_month <= 31:
            raise InvalidScheduleError("A day of the month is from 1 to 31.")
        if (frequency in DATED_FREQUENCIES) != (self.start_date is not None):
            raise InvalidScheduleError(
                "A one-time or interval schedule has a date; other schedules do not."
            )
        if (frequency is ScheduleFrequency.INTERVAL) != (self.interval_hours is not None):
            raise InvalidScheduleError(
                "An interval schedule says how many hours apart it runs; others do not."
            )
        if self.interval_hours is not None and not (
            MIN_INTERVAL_HOURS <= self.interval_hours <= MAX_INTERVAL_HOURS
        ):
            raise InvalidScheduleError(
                f"An interval is from {MIN_INTERVAL_HOURS} to {MAX_INTERVAL_HOURS} hours."
            )
        load_timezone(self.timezone_name)

    @property
    def interval(self) -> timedelta | None:
        """The time between runs of an interval rule; None for calendar rules."""
        return timedelta(hours=self.interval_hours) if self.interval_hours is not None else None

    def next_after(self, after: datetime) -> datetime | None:
        """The first instant the rule fires strictly after ``after``, in UTC, or None when
        it never fires again (a one-time rule whose moment has passed)."""
        if after.tzinfo is None:
            raise ValueError("after must be timezone-aware")
        zone = ZoneInfo(self.timezone_name)

        if self.frequency is ScheduleFrequency.ONCE:
            assert self.start_date is not None
            slot = self._instant(self.start_date, zone)
            return slot if slot > after else None

        if self.frequency is ScheduleFrequency.INTERVAL:
            assert self.start_date is not None and self.interval is not None
            first = self._instant(self.start_date, zone)
            if after < first:
                return first
            return first + ((after - first) // self.interval + 1) * self.interval

        first_day = after.astimezone(zone).date()
        for offset in range(_SEARCH_DAYS + 1):
            day = first_day + timedelta(days=offset)
            if not self._fires_on(day):
                continue
            candidate = self._instant(day, zone)
            if candidate > after:
                return candidate
        raise AssertionError("a calendar rule always fires within two months")  # pragma: no cover

    def _instant(self, day: date, zone: ZoneInfo) -> datetime:
        return datetime.combine(day, self.local_time, tzinfo=zone).astimezone(UTC)

    def _fires_on(self, day: date) -> bool:
        if self.frequency is ScheduleFrequency.WEEKLY:
            return any(day.weekday() == weekday_number(weekday) for weekday in self.weekdays)
        if self.frequency is ScheduleFrequency.MONTHLY:
            assert self.day_of_month is not None
            last_day = calendar.monthrange(day.year, day.month)[1]
            return day.day == min(self.day_of_month, last_day)
        return True


@dataclass(frozen=True, slots=True)
class RuleFields:
    """A rule as a request or a proposal states it. ``build`` checks it and fills in what
    an interval rule may leave out: without a date it starts today, in its timezone."""

    frequency: ScheduleFrequency
    local_time: time
    timezone: str
    weekdays: tuple[Weekday, ...] = ()
    day_of_month: int | None = None
    start_date: date | None = None
    interval_hours: int | None = None

    def build(self, now: datetime) -> ScheduleRule:
        start_date = self.start_date
        if self.frequency is ScheduleFrequency.INTERVAL and start_date is None:
            start_date = now.astimezone(load_timezone(self.timezone)).date()
        return ScheduleRule(
            frequency=self.frequency,
            local_time=self.local_time,
            timezone_name=self.timezone,
            weekdays=self.weekdays,
            day_of_month=self.day_of_month,
            start_date=start_date,
            interval_hours=self.interval_hours,
        )
