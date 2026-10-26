"""Today: what the Feed puts first, each card something to act on (ADR-048).

* Next actions: what is overdue, due or reminded today, then promises to people, then
  what is due this week. Undated to-dos wait in the To do list; they are not today's.
* Promises: open items that involve a person, since letting someone down costs more than
  forgetting an errand.
* Meetings: calendar events of today and tomorrow, each with what the user's memories
  say about the people it names.
* Resurfacing: one idea, intention, or goal noted weeks ago and untouched since, a
  different one each day: "still on?".
* To confirm: the newest memories the pipeline was unsure of, a few at a time.

Ranking is rules over the user's own records, without a model, so it costs nothing and
never invents a priority.
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from app.domain.enums import MemoryType

MAX_NEXT_ACTIONS: Final = 5
MAX_PROMISES: Final = 3
MAX_MEETINGS: Final = 3
MAX_RELATED: Final = 3
MAX_TO_CONFIRM: Final = 3
UPCOMING_DAYS: Final = 7
# A memory resurfaces once it is this old and nobody touched it for as long.
RESURFACE_AFTER: Final = timedelta(days=14)
RESURFACE_UNTIL: Final = timedelta(days=120)
RESURFACE_TYPES: Final = frozenset(
    {MemoryType.IDEA, MemoryType.INTENTION, MemoryType.GOAL, MemoryType.PROJECT}
)
# Names shorter than this match too many ordinary words.
MIN_NAME_CHARS: Final = 3


@dataclass(frozen=True, slots=True)
class ActionCandidate:
    memory_id: uuid.UUID
    due_on: date | None
    # The local day of a pending reminder.
    remind_on: date | None
    # Whether it involves a person: a promise, not an errand.
    with_person: bool


def next_action_rank(candidate: ActionCandidate, today: date) -> tuple[int, int] | None:
    """Where an open item ranks among today's next actions; None when it is not today's
    business. Lower ranks first; ties go to the earlier date."""
    due = candidate.due_on
    if due is not None and due < today:
        return (0, due.toordinal())
    if due == today or candidate.remind_on == today:
        return (1, today.toordinal())
    if candidate.with_person and due is None:
        return (2, 0)
    if due is not None and due <= today + timedelta(days=UPCOMING_DAYS):
        return (2 if candidate.with_person else 3, due.toordinal())
    return None


def next_actions(candidates: Sequence[ActionCandidate], today: date) -> list[uuid.UUID]:
    """Today's next actions, most pressing first, at most ``MAX_NEXT_ACTIONS``."""
    ranked = [
        (rank, index, candidate.memory_id)
        for index, candidate in enumerate(candidates)
        if (rank := next_action_rank(candidate, today)) is not None
    ]
    ranked.sort()
    return [memory_id for _, _, memory_id in ranked[:MAX_NEXT_ACTIONS]]


def pick_of_the_day(ids: Sequence[uuid.UUID], today: date) -> uuid.UUID | None:
    """One of ``ids``, the same all day and a different one the next."""
    if not ids:
        return None
    ordered = sorted(ids, key=str)
    return ordered[today.toordinal() % len(ordered)]


def names_in(text: str, names: Mapping[uuid.UUID, str]) -> list[uuid.UUID]:
    """The entities whose name appears in ``text`` as whole words, in name order."""
    found = []
    lowered = text.lower()
    for entity_id, name in sorted(names.items(), key=lambda item: item[1].lower()):
        cleaned = name.strip().lower()
        if len(cleaned) < MIN_NAME_CHARS:
            continue
        if re.search(rf"(?<!\w){re.escape(cleaned)}(?!\w)", lowered):
            found.append(entity_id)
    return found
