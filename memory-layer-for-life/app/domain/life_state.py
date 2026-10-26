"""Life state: what is open in the user's life now, and the rules of the daily brief.
None of it needs a database or a model.

An *open item* is a live memory (proposed or active) of a kind someone acts on (a task,
commitment, open loop, plan, intention, goal, or project) whose state is open or
planned and that nobody closed. Its due date (``due_on``) comes from the extractor's
resolved date or from the user. Closing it records why: done or dropped.

The daily brief is composed from the life state alone, without a model: what is due
today, what is overdue, what was due yesterday and is still open (the follow-up), what
is coming this week, items gone quiet, today's reminders, and how many memories wait for
review. It is sent once per local day at the user's chosen time, and a slot found more
than ``BRIEF_GRACE`` late is skipped rather than sent hours late.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Final

from app.domain.enums import LifeBucket, MemoryState, MemoryType

# Kinds of memory someone acts on; goals and projects are long-running.
ACTIONABLE_TYPES: Final = frozenset(
    {
        MemoryType.TASK,
        MemoryType.COMMITMENT,
        MemoryType.OPEN_LOOP,
        MemoryType.PLAN,
        MemoryType.INTENTION,
    }
)
LONG_TERM_TYPES: Final = frozenset({MemoryType.GOAL, MemoryType.PROJECT})
LIFE_TYPES: Final = ACTIONABLE_TYPES | LONG_TERM_TYPES
# Open questions and unresolved problems: open, but nothing to tick off. Listed apart from
# the to-dos (ADR-048).
QUESTION_TYPES: Final = frozenset({MemoryType.OPEN_LOOP})
# What the brief counts as new to review: memories proposed in the last week. Older ones
# are the backlog of earlier versions of the pipeline, not news.
REVIEW_NEWS_WINDOW: Final = timedelta(days=7)
# States of an item still to do. Goals and projects often have no state, so theirs counts.
OPEN_STATES: Final = frozenset({MemoryState.OPEN, MemoryState.PLANNED})
LONG_TERM_OPEN_STATES: Final = OPEN_STATES | {MemoryState.NOT_APPLICABLE}

UPCOMING_DAYS: Final = 7
# An open item nobody touched for this long is "gone quiet".
STALE_AFTER: Final = timedelta(days=14)
# A brief found later than this after its time is skipped for the day.
BRIEF_GRACE: Final = timedelta(hours=3)
# How many items of each kind the brief lists.
BRIEF_ITEMS: Final = 5


def bucket_for(due_on: date | None, today: date) -> LifeBucket:
    if due_on is None:
        return LifeBucket.SOMEDAY
    if due_on < today:
        return LifeBucket.OVERDUE
    if due_on == today:
        return LifeBucket.TODAY
    if due_on <= today + timedelta(days=UPCOMING_DAYS):
        return LifeBucket.UPCOMING
    return LifeBucket.LATER


def is_stale(*, due_on: date | None, last_activity: datetime, now: datetime, today: date) -> bool:
    """An open item gone quiet: untouched for ``STALE_AFTER`` and not due in the future."""
    if due_on is not None and due_on >= today:
        return False
    return now - last_activity >= STALE_AFTER


def in_quiet_hours(local: time, start: time | None, end: time | None) -> bool:
    """Whether a local time falls in the user's quiet hours, which may wrap past midnight
    (22:00 to 07:00). Start is inclusive, end exclusive; equal bounds mean none."""
    if start is None or end is None or start == end:
        return False
    if start < end:
        return start <= local < end
    return local >= start or local < end


def brief_due(local_now: datetime, brief_time: time, last_brief_on: date | None) -> bool:
    """Whether today's brief should go now: its time has come, not more than
    ``BRIEF_GRACE`` ago, and none went today. ``local_now`` is in the user's timezone."""
    today = local_now.date()
    if last_brief_on is not None and last_brief_on >= today:
        return False
    slot = datetime.combine(today, brief_time, tzinfo=local_now.tzinfo)
    return slot <= local_now < slot + BRIEF_GRACE


def next_brief_at(local_now: datetime, brief_time: time, last_brief_on: date | None) -> datetime:
    """When the user's next brief is due, in their timezone: now when one is due, else
    today's time if it is still ahead and none went today, else tomorrow's."""
    if brief_due(local_now, brief_time, last_brief_on):
        return local_now
    today = local_now.date()
    slot = datetime.combine(today, brief_time, tzinfo=local_now.tzinfo)
    if slot > local_now and (last_brief_on is None or last_brief_on < today):
        return slot
    return datetime.combine(today + timedelta(days=1), brief_time, tzinfo=local_now.tzinfo)


@dataclass(frozen=True, slots=True)
class BriefItem:
    memory_id: uuid.UUID
    content: str
    due_on: date | None = None


@dataclass(frozen=True, slots=True)
class BriefReminder:
    memory_id: uuid.UUID
    content: str
    # When, in the user's timezone.
    at: time


@dataclass(frozen=True, slots=True)
class BriefInputs:
    today: date
    user_name: str | None
    due_today: Sequence[BriefItem] = ()
    overdue: Sequence[BriefItem] = ()
    # Due yesterday and still open: did they get done?
    follow_ups: Sequence[BriefItem] = ()
    upcoming: Sequence[BriefItem] = ()
    stale: Sequence[BriefItem] = ()
    reminders: Sequence[BriefReminder] = ()
    review_count: int = 0
    # On Mondays: how many items were done in the past seven days (ADR-046).
    last_week_done: int = 0


@dataclass(frozen=True, slots=True)
class Brief:
    text: str
    # A short line for a notification.
    summary: str
    # Items the brief asks about, so the app can offer Done and Not yet beside them.
    follow_ups: tuple[BriefItem, ...] = field(default_factory=tuple)
    # Nothing due, open, coming, or waiting for review: no brief is worth sending.
    nothing_to_say: bool = False


NOTHING_DUE: Final = "Nothing is due today."


def _day(value: date) -> str:
    return f"{value:%a} {value.day} {value:%b}"


def _list(title: str, items: Sequence[str]) -> list[str]:
    if not items:
        return []
    return ["", f"**{title}**", *(f"- {item}" for item in items)]


def compose_brief(inputs: BriefInputs) -> Brief:
    """The daily brief as Markdown for the chat, and a one-line summary for a push."""
    greeting = f"Good morning, {inputs.user_name}." if inputs.user_name else "Good morning."
    lines = [f"{greeting} Here's {inputs.today:%A}, {inputs.today.day} {inputs.today:%B}."]
    if inputs.last_week_done:
        noun = "thing" if inputs.last_week_done == 1 else "things"
        lines.append(f"Last week you finished {inputs.last_week_done} {noun} on your list.")
    lines += _list("Due today", [item.content for item in inputs.due_today[:BRIEF_ITEMS]])
    lines += _list(
        "Overdue",
        [
            f"{item.content} (due {_day(item.due_on)})" if item.due_on else item.content
            for item in inputs.overdue[:BRIEF_ITEMS]
        ],
    )
    follow_ups = inputs.follow_ups[:BRIEF_ITEMS]
    lines += _list("Did these get done?", [item.content for item in follow_ups])
    lines += _list(
        "Coming up this week",
        [
            f"{item.content} ({_day(item.due_on)})" if item.due_on else item.content
            for item in inputs.upcoming[:BRIEF_ITEMS]
        ],
    )
    lines += _list(
        "Reminders today",
        [f"{reminder.at:%H:%M} {reminder.content}" for reminder in inputs.reminders[:BRIEF_ITEMS]],
    )
    lines += _list("Still on?", [item.content for item in inputs.stale[:3]])

    counts = []
    if inputs.due_today:
        counts.append(f"{len(inputs.due_today)} due today")
    if inputs.overdue:
        counts.append(f"{len(inputs.overdue)} overdue")
    if inputs.follow_ups:
        counts.append(f"{len(inputs.follow_ups)} to check off")
    summary = " · ".join(counts) if counts else NOTHING_DUE
    if not counts:
        lines += ["", NOTHING_DUE + (" Enjoy your day." if not inputs.upcoming else "")]
    if inputs.review_count:
        noun = "memory" if inputs.review_count == 1 else "memories"
        lines += ["", f"{inputs.review_count} new {noun} to review in Memories."]
    return Brief(
        text="\n".join(lines),
        summary=summary,
        follow_ups=tuple(follow_ups),
        nothing_to_say=not (
            inputs.due_today
            or inputs.overdue
            or inputs.follow_ups
            or inputs.upcoming
            or inputs.reminders
            or inputs.stale
            or inputs.review_count
            or inputs.last_week_done
        ),
    )
