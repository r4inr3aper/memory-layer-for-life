"""The assistant's tools for the user's life state: reminders, what is open, and checking
things off.

A reminder is a task memory with a time: at that time the app posts it to chat and pushes
it, without running the assistant, so it costs no prompt. It differs from a schedule,
which runs the assistant to do work. The user asked for it, so it needs no confirmation
card. Sensitive items are never listed: the model must not see them.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Final, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, ValidationError

from app.core.clock import Clock, utc_now
from app.domain.enums import LifeBucket
from app.domain.errors import DomainError
from app.domain.schedule_rules import parse_local_date, parse_local_time
from app.integrations.assistant.base import ToolDefinition
from app.services.assistant.context import TurnContext
from app.services.assistant.tool_base import ToolInput, ToolOutput, invalid_input
from app.services.life_state import LifeOverview, LifeStateService
from app.services.queries import MemoryView

_MAX_LISTED: Final = 10
_BUCKET_TITLES: Final = (
    (LifeBucket.OVERDUE, "Overdue"),
    (LifeBucket.TODAY, "Due today"),
    (LifeBucket.UPCOMING, "This week"),
    (LifeBucket.LATER, "Later"),
    (LifeBucket.SOMEDAY, "No date"),
)


def _local(day: str, at: str, timezone_name: str) -> tuple[date, datetime]:
    local_day = parse_local_date(day)
    return local_day, datetime.combine(
        local_day, parse_local_time(at), tzinfo=ZoneInfo(timezone_name)
    )


def _when(moment: datetime, timezone_name: str) -> str:
    local = moment.astimezone(ZoneInfo(timezone_name))
    return f"{local:%a} {local.day} {local:%b} at {local:%H:%M}"


class CreateReminderInput(ToolInput):
    text: str = Field(min_length=1, max_length=300)
    date: str
    time: str


class CreateReminderTool:
    label = "Setting a reminder"
    definition = ToolDefinition(
        name="create_reminder",
        description=(
            "Save something the user asked to be reminded of, at a date and time. At that time "
            "the app posts it in chat and sends a notification. Use it for plain reminders "
            "('remind me to call Mum at 6'); use propose_schedule only when work must be done "
            "at that time."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "What to remind them of, as a short task: 'Call Mum'.",
                },
                "date": {"type": "string", "description": "YYYY-MM-DD in the user's calendar."},
                "time": {"type": "string", "description": "HH:MM, 24-hour, user's local time."},
            },
            "required": ["text", "date", "time"],
        },
    )

    def __init__(self, life: LifeStateService) -> None:
        self._life = life

    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput:
        try:
            parsed = CreateReminderInput.model_validate(arguments)
            day, remind_at = _local(parsed.date, parsed.time, turn.timezone_name)
            saved = await self._life.create_reminder(
                turn.principal, content=parsed.text, remind_at=remind_at, due_on=day
            )
        except ValidationError as error:
            return invalid_input(error)
        except DomainError as error:
            return ToolOutput(error.message, is_error=True)
        return ToolOutput(
            f"Saved. The user will be reminded to '{saved.content}' on "
            f"{_when(remind_at, turn.timezone_name)}. Confirm it in one short sentence."
        )


class ListOpenItemsTool:
    label = "Checking your list"
    definition = ToolDefinition(
        name="list_open_items",
        description=(
            "The user's open tasks, plans, and commitments by when they are due, their goals, "
            "and pending reminders. Each item has an id for update_open_item; never show ids."
        ),
        input_schema={"type": "object", "properties": {}},
    )

    def __init__(self, life: LifeStateService) -> None:
        self._life = life

    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput:
        overview = await self._life.overview(turn.principal, include_sensitive=False)
        return ToolOutput(format_overview(overview, timezone_name=turn.timezone_name))


def _line(view: MemoryView) -> str:
    due = f" (due {view.due_on:%a %d %b})" if view.due_on else ""
    return f"- {view.content}{due} [id {view.id}]"


def format_overview(overview: LifeOverview, *, timezone_name: str) -> str:
    sections: list[str] = [f"Today is {overview.today:%A %d %B %Y}."]

    def add(title: str, views: Sequence[MemoryView]) -> None:
        if views:
            sections.append(f"{title}:\n" + "\n".join(_line(view) for view in views[:_MAX_LISTED]))

    for bucket, title in _BUCKET_TITLES:
        add(title, overview.buckets[bucket])
    add("Goals and projects", overview.goals)
    if overview.reminders:
        sections.append(
            "Reminders:\n"
            + "\n".join(
                f"- {view.content} on {_when(view.remind_at, timezone_name)} [id {view.id}]"
                for view in overview.reminders[:_MAX_LISTED]
                if view.remind_at is not None
            )
        )
    if len(sections) == 1:
        sections.append("Nothing is open. Say so, and do not invent items.")
    return "\n\n".join(sections)


class UpdateOpenItemInput(ToolInput):
    item_id: uuid.UUID
    action: Literal["done", "drop", "reopen", "snooze"]
    date: str | None = None
    time: str | None = None


class UpdateOpenItemTool:
    label = "Updating your list"
    definition = ToolDefinition(
        name="update_open_item",
        description=(
            "Change an item from list_open_items when the user says so: 'done' when they did "
            "it, 'drop' when they will not do it, 'reopen' to undo either, 'snooze' to be "
            "reminded at a later date and time."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "The id from list_open_items."},
                "action": {"type": "string", "enum": ["done", "drop", "reopen", "snooze"]},
                "date": {"type": "string", "description": "For snooze: YYYY-MM-DD, local."},
                "time": {"type": "string", "description": "For snooze: HH:MM, local."},
            },
            "required": ["item_id", "action"],
        },
    )

    def __init__(self, life: LifeStateService, *, clock: Clock = utc_now) -> None:
        self._life = life
        self._clock = clock

    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput:
        try:
            parsed = UpdateOpenItemInput.model_validate(arguments)
            if parsed.action == "done":
                view = await self._life.complete(turn.principal, parsed.item_id)
                return ToolOutput(f"Marked done: {view.content}.")
            if parsed.action == "drop":
                view = await self._life.drop(turn.principal, parsed.item_id)
                return ToolOutput(f"No longer tracked: {view.content}.")
            if parsed.action == "reopen":
                view = await self._life.reopen(turn.principal, parsed.item_id)
                return ToolOutput(f"Open again: {view.content}.")
            if parsed.date is None or parsed.time is None:
                return ToolOutput("Snoozing needs a date and a time.", is_error=True)
            _, remind_at = _local(parsed.date, parsed.time, turn.timezone_name)
            view = await self._life.snooze(turn.principal, parsed.item_id, remind_at)
        except ValidationError as error:
            return invalid_input(error)
        except DomainError as error:
            return ToolOutput(error.message, is_error=True)
        return ToolOutput(f"Snoozed: {view.content}, until {_when(remind_at, turn.timezone_name)}.")
