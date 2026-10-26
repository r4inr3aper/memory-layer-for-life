"""Insights: what the user's own memories show over time, computed without a model.

Each insight is grounded: it names the memories it rests on, so the app can show why.
Each has a stable key per period (``money:2026-10``, ``people.quiet:<id>:2026-10``), so
feedback on it ("not useful") hides that insight for the period and no longer.

Kinds:

* ``money``: amounts noted this month, by category, against last month (per currency).
* ``people.top``: the people mentioned most in the last 30 days.
* ``people.quiet``: someone mentioned often before who has not come up for 30 days.
* ``follow_through``: open items done, dropped, and overdue over the last 30 days, with
  the run of consecutive days with something done.
* ``goal.quiet``: an open goal or project nobody touched for 30 days.
* ``theme``: a topic, project, or concept mentioned several times this week.

Each kind needs enough evidence before it says anything (ADR-048): a total of a handful of
money notes, a follow-through rate when the user has never ticked anything off, or a
"person" who only appears in expense shorthand ("raju biryani") would be confident claims
built on noise. People come only from memories about what the user does with them, never
from money notes, saved links, or working notes.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Final

from app.domain.enums import InsightKind, InsightTarget

WINDOW: Final = timedelta(days=30)
# Mentioned at least this often before to be missed when quiet.
QUIET_PERSON_MIN_MENTIONS: Final = 3
TOP_PEOPLE: Final = 3
THEME_MIN_MENTIONS: Final = 3
# Done, dropped, and overdue together must reach this before a rate means anything, and
# the user must have closed something themselves: a rate is about what they tick off.
FOLLOW_THROUGH_MIN_ITEMS: Final = 5
FOLLOW_THROUGH_MIN_CLOSED: Final = 1
# Money notes needed in a month before its total is shown, or compared with.
MONEY_MIN_NOTES: Final = 5
MAX_EVIDENCE: Final = 20


@dataclass(frozen=True, slots=True)
class Insight:
    key: str
    kind: InsightKind
    title: str
    body: str
    memory_ids: tuple[uuid.UUID, ...] = ()
    target: InsightTarget = InsightTarget.MEMORIES
    target_id: uuid.UUID | None = None
    # Larger first in the list.
    weight: float = 0.0


@dataclass(frozen=True, slots=True)
class MoneyNote:
    memory_id: uuid.UUID
    happened_on: date
    amount: float
    currency: str | None
    category: str | None


@dataclass(frozen=True, slots=True)
class Mention:
    """A live memory mentioning an entity."""

    memory_id: uuid.UUID
    entity_id: uuid.UUID
    entity_name: str
    entity_type: str
    happened_at: datetime


@dataclass(frozen=True, slots=True)
class Closure:
    memory_id: uuid.UUID
    closed_on: date
    done: bool


@dataclass(frozen=True, slots=True)
class OpenGoal:
    memory_id: uuid.UUID
    content: str
    last_activity: datetime


@dataclass(frozen=True, slots=True)
class InsightInputs:
    today: date
    now: datetime
    money: Sequence[MoneyNote] = ()
    mentions: Sequence[Mention] = ()
    closures: Sequence[Closure] = ()
    overdue_ids: Sequence[uuid.UUID] = ()
    goals: Sequence[OpenGoal] = ()
    # Keys the user marked not useful.
    hidden: frozenset[str] = field(default_factory=frozenset)


def _month(day: date) -> str:
    return f"{day:%Y-%m}"


def _week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _amount(value: float, currency: str | None) -> str:
    number = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    return f"{currency} {number}" if currency else number


def money_insights(notes: Sequence[MoneyNote], today: date) -> list[Insight]:
    """One insight per currency noted this month, compared with last month."""
    this_month = today.replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    by_currency: dict[str | None, list[MoneyNote]] = defaultdict(list)
    previous: dict[str | None, float] = defaultdict(float)
    for note in notes:
        if note.happened_on >= this_month:
            by_currency[note.currency].append(note)
        elif note.happened_on >= last_month:
            previous[note.currency] += note.amount
    counts: dict[str | None, int] = defaultdict(int)
    for note in notes:
        if last_month <= note.happened_on < this_month:
            counts[note.currency] += 1
    insights = []
    for currency, current in by_currency.items():
        if len(current) < MONEY_MIN_NOTES:
            continue
        total = sum(note.amount for note in current)
        categories: dict[str, float] = defaultdict(float)
        for note in current:
            categories[note.category or "other"] += note.amount
        biggest = sorted(categories.items(), key=lambda pair: (-pair[1], pair[0]))[:3]
        top = ", ".join(f"{name} {_amount(value, currency)}" for name, value in biggest)
        body = f"{len(current)} money notes this month: {top}."
        before = previous.get(currency) if counts[currency] >= MONEY_MIN_NOTES else None
        if before:
            change = (total - before) / before * 100
            body += f" Last month: {_amount(before, currency)} ({change:+.0f}%)."
        insights.append(
            Insight(
                key=f"money:{_month(today)}:{currency or 'none'}",
                kind=InsightKind.MONEY,
                title=f"{_amount(total, currency)} noted this month",
                body=body,
                memory_ids=tuple(note.memory_id for note in current[:MAX_EVIDENCE]),
                weight=2.0,
            )
        )
    return insights


def people_insights(mentions: Sequence[Mention], now: datetime, today: date) -> list[Insight]:
    people = [mention for mention in mentions if mention.entity_type == "person"]
    recent_since = now - WINDOW
    recent: dict[uuid.UUID, list[Mention]] = defaultdict(list)
    earlier: dict[uuid.UUID, list[Mention]] = defaultdict(list)
    for mention in people:
        (recent if mention.happened_at >= recent_since else earlier)[mention.entity_id].append(
            mention
        )
    insights: list[Insight] = []
    top = sorted(recent.items(), key=lambda pair: (-len(pair[1]), pair[1][0].entity_name))
    top = [pair for pair in top if len(pair[1]) >= 2][:TOP_PEOPLE]
    if top:
        names = ", ".join(f"{group[0].entity_name} ({len(group)})" for _, group in top)
        insights.append(
            Insight(
                key=f"people.top:{_week(today)}",
                kind=InsightKind.PEOPLE_TOP,
                title=f"On your mind: {top[0][1][0].entity_name}",
                body=f"Mentioned most in the last 30 days: {names}.",
                memory_ids=tuple(m.memory_id for _, group in top for m in group)[:MAX_EVIDENCE],
                target=InsightTarget.PERSON,
                target_id=top[0][0],
                weight=1.0,
            )
        )
    for entity_id, group in earlier.items():
        if entity_id in recent or len(group) < QUIET_PERSON_MIN_MENTIONS:
            continue
        last = max(mention.happened_at for mention in group)
        weeks = (now - last).days // 7
        name = group[0].entity_name
        insights.append(
            Insight(
                key=f"people.quiet:{entity_id}:{_month(today)}",
                kind=InsightKind.PEOPLE_QUIET,
                title=f"You haven't mentioned {name} in {weeks} weeks",
                body=f"{name} came up in {len(group)} memories before that.",
                memory_ids=tuple(m.memory_id for m in group)[:MAX_EVIDENCE],
                target=InsightTarget.PERSON,
                target_id=entity_id,
                weight=1.5 + min(len(group), 10) / 10,
            )
        )
    return insights


def streak(closures: Sequence[Closure], today: date) -> int:
    """Consecutive days, ending today or yesterday, with at least one item done."""
    days = {closure.closed_on for closure in closures if closure.done}
    current = today if today in days else today - timedelta(days=1)
    count = 0
    while current in days:
        count += 1
        current -= timedelta(days=1)
    return count


def follow_through_insight(
    closures: Sequence[Closure], overdue_ids: Sequence[uuid.UUID], today: date
) -> Insight | None:
    since = today - timedelta(days=WINDOW.days)
    window = [closure for closure in closures if closure.closed_on >= since]
    done = [closure for closure in window if closure.done]
    dropped = [closure for closure in window if not closure.done]
    considered = len(done) + len(dropped) + len(overdue_ids)
    if (
        considered < FOLLOW_THROUGH_MIN_ITEMS
        or len(done) + len(dropped) < FOLLOW_THROUGH_MIN_CLOSED
    ):
        return None
    rate = round(len(done) / considered * 100)
    days = streak(closures, today)
    parts = [f"{len(done)} done", f"{len(dropped)} dropped", f"{len(overdue_ids)} overdue"]
    body = "In the last 30 days: " + ", ".join(parts) + "."
    if days >= 2:
        body += f" You've finished something {days} days in a row."
    return Insight(
        key=f"follow_through:{_week(today)}",
        kind=InsightKind.FOLLOW_THROUGH,
        title=f"You finish {rate}% of what you plan",
        body=body,
        memory_ids=tuple([closure.memory_id for closure in window] + list(overdue_ids))[
            :MAX_EVIDENCE
        ],
        target=InsightTarget.TODO,
        weight=1.8 if overdue_ids else 1.2,
    )


def goal_insights(goals: Sequence[OpenGoal], now: datetime, today: date) -> list[Insight]:
    insights = []
    for goal in goals:
        idle = now - goal.last_activity
        if idle < WINDOW:
            continue
        insights.append(
            Insight(
                key=f"goal.quiet:{goal.memory_id}:{_month(today)}",
                kind=InsightKind.GOAL_QUIET,
                title=f"“{goal.content}” has been quiet for {idle.days // 7} weeks",
                body="Still a goal? Mark it done, drop it, or tell Cooper what's next.",
                memory_ids=(goal.memory_id,),
                target=InsightTarget.MEMORY,
                target_id=goal.memory_id,
                weight=1.6,
            )
        )
    return insights


THEME_TYPES: Final = frozenset({"topic", "project", "concept", "technology", "organization"})


def theme_insights(mentions: Sequence[Mention], now: datetime, today: date) -> list[Insight]:
    since = now - timedelta(days=7)
    groups: dict[uuid.UUID, list[Mention]] = defaultdict(list)
    for mention in mentions:
        if mention.entity_type in THEME_TYPES and mention.happened_at >= since:
            groups[mention.entity_id].append(mention)
    insights = []
    for entity_id, group in groups.items():
        if len(group) < THEME_MIN_MENTIONS:
            continue
        name = group[0].entity_name
        insights.append(
            Insight(
                key=f"theme:{entity_id}:{_week(today)}",
                kind=InsightKind.THEME,
                title=f"{name} keeps coming up",
                body=f"Mentioned in {len(group)} memories this week.",
                memory_ids=tuple(m.memory_id for m in group)[:MAX_EVIDENCE],
                target=InsightTarget.PERSON,
                target_id=entity_id,
                weight=0.8 + len(group) / 10,
            )
        )
    return insights


def compute_insights(inputs: InsightInputs) -> list[Insight]:
    """Every insight the inputs support, strongest first, without hidden ones."""
    found: list[Insight] = []
    found += money_insights(inputs.money, inputs.today)
    found += people_insights(inputs.mentions, inputs.now, inputs.today)
    follow = follow_through_insight(inputs.closures, inputs.overdue_ids, inputs.today)
    if follow is not None:
        found.append(follow)
    found += goal_insights(inputs.goals, inputs.now, inputs.today)
    found += theme_insights(inputs.mentions, inputs.now, inputs.today)
    visible = [insight for insight in found if insight.key not in inputs.hidden]
    return sorted(visible, key=lambda insight: (-insight.weight, insight.key))
