"""Scheduled tasks as the user sees them: confirm a proposal or write one, list, edit,
pause, resume, cancel, delete, and run now.

A schedule comes into existence by confirming a proposal the assistant made in chat, or
from the app's form. A proposal is read from the stored message, never from the request,
so what gets scheduled is exactly what the user was shown.

Results go to chat, or to a connected app: a schedule can only be given an app the user
has connected (as last seen), and a run checks the connection again before it starts.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import (
    ProposalStatus,
    ScheduleDelivery,
    ScheduleFrequency,
    ScheduleRunStatus,
    ScheduleRunTrigger,
    ScheduleStatus,
    Weekday,
)
from app.domain.errors import (
    InvalidScheduleError,
    RecordNotFoundError,
    ScheduleRunInProgressError,
)
from app.domain.principal import Principal
from app.domain.schedule_rules import RuleFields, ScheduleRule, parse_local_time
from app.domain.tool_catalog import DELIVERY_TOOLKITS, find_tool
from app.models.chat_message import ChatMessage
from app.models.scheduled_task import ScheduledTask
from app.models.scheduled_task_run import ScheduledTaskRun
from app.repositories.chat_repository import ChatRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.schemas.message_metadata import MessageMetadata
from app.services.background import BackgroundWork
from app.services.chat import existing_message, existing_thread, pending_proposal
from app.services.schedule_runs import ScheduleRunner, rule_columns, rule_of
from app.services.tool_connections import ToolConnectionService

PAST_SLOT_MESSAGE = "That time has already passed. Pick a time in the future."


@dataclass(frozen=True, slots=True)
class RuleChanges:
    """Rule fields to change; None leaves a field as it is. Fields the new frequency does
    not use are dropped when the frequency changes."""

    frequency: ScheduleFrequency | None = None
    local_time: time | None = None
    timezone: str | None = None
    weekdays: tuple[Weekday, ...] | None = None
    day_of_month: int | None = None
    start_date: date | None = None
    interval_hours: int | None = None

    def apply_to(self, current: ScheduleRule) -> RuleFields:
        frequency = self.frequency or current.frequency
        kept = frequency is current.frequency
        return RuleFields(
            frequency=frequency,
            local_time=self.local_time or current.local_time,
            timezone=self.timezone or current.timezone_name,
            weekdays=(
                self.weekdays if self.weekdays is not None else current.weekdays if kept else ()
            ),
            day_of_month=_changed(self.day_of_month, current.day_of_month, kept),
            start_date=_changed(self.start_date, current.start_date, kept),
            interval_hours=_changed(self.interval_hours, current.interval_hours, kept),
        )


@dataclass(frozen=True, slots=True)
class NewSchedule:
    """A schedule the user writes themselves, rather than confirming a proposal."""

    title: str
    task: str
    rule: RuleFields
    delivery: ScheduleDelivery
    delivery_target: str | None = None


@dataclass(frozen=True, slots=True)
class ScheduleChanges:
    """An edit. None leaves a field as it is; ``delivery_target_given`` tells clearing the
    target apart from leaving it."""

    title: str | None = None
    task: str | None = None
    rule: RuleChanges | None = None
    delivery: ScheduleDelivery | None = None
    delivery_target: str | None = None
    delivery_target_given: bool = False
    status: ScheduleStatus | None = None


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    """A finished run, for the feed: the run, its schedule, and where the result went."""

    run: ScheduledTaskRun
    task: ScheduledTask
    thread_id: uuid.UUID | None


class ScheduleService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: ScheduleRunner,
        background: BackgroundWork,
        *,
        connections: ToolConnectionService,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._background = background
        self._connections = connections
        self._clock = clock

    async def list_schedules(
        self, principal: Principal, *, limit: int, offset: int
    ) -> tuple[list[tuple[ScheduledTask, int]], int]:
        async with self._session_factory() as session:
            return await ScheduleRepository(session).list_for_user(
                principal.id, limit=limit, offset=offset
            )

    async def get(self, principal: Principal, task_id: uuid.UUID) -> tuple[ScheduledTask, int]:
        async with self._session_factory() as session:
            schedules = ScheduleRepository(session)
            task = await _existing(schedules, principal, task_id)
            return task, await schedules.run_count(task.id)

    async def confirm_proposal(
        self, principal: Principal, thread_id: uuid.UUID, message_id: uuid.UUID
    ) -> tuple[ScheduledTask, ChatMessage]:
        """Create the schedule a message proposes, and mark the proposal confirmed.

        Both happen in one transaction with the message locked, so a proposal becomes at
        most one schedule even when confirmed twice at once.
        """
        now = self._clock()
        async with transaction(self._session_factory) as session:
            chat = ChatRepository(session)
            thread = await existing_thread(chat, principal, thread_id)
            message = await existing_message(chat, thread_id, message_id)
            metadata = MessageMetadata.from_json(message.metadata_)
            proposal = pending_proposal(metadata)
            rule = RuleFields(
                frequency=proposal.frequency,
                local_time=parse_local_time(proposal.local_time),
                timezone=proposal.timezone,
                weekdays=proposal.rule_weekdays(),
                day_of_month=proposal.day_of_month,
                start_date=proposal.start_date,
                interval_hours=proposal.interval_hours,
            ).build(now)
            await self._require_deliverable(principal, proposal.delivery)
            task = await ScheduleRepository(session).add(
                ScheduledTask(
                    id=new_uuid(),
                    user_id=principal.id,
                    source_thread_id=thread.id,
                    title=proposal.title,
                    original_prompt=proposal.original_prompt,
                    task=proposal.task,
                    **rule_columns(rule),
                    delivery=proposal.delivery.value,
                    delivery_target=proposal.delivery_target,
                    status=ScheduleStatus.ACTIVE.value,
                    next_run_at=_first_slot(rule, now),
                    created_at=now,
                    updated_at=now,
                )
            )
            metadata.schedule_proposal = proposal.model_copy(
                update={"status": ProposalStatus.CONFIRMED, "scheduled_task_id": task.id}
            )
            message.metadata_ = metadata.to_json()
            message.updated_at = now
            return task, message

    async def create(self, principal: Principal, new: NewSchedule) -> tuple[ScheduledTask, int]:
        """Create a schedule from the user's own form. Results delivered to chat go to the
        main thread, since the schedule did not come from a conversation."""
        now = self._clock()
        rule = new.rule.build(now)
        first = _first_slot(rule, now)
        await self._require_deliverable(principal, new.delivery)
        async with transaction(self._session_factory) as session:
            task = await ScheduleRepository(session).add(
                ScheduledTask(
                    id=new_uuid(),
                    user_id=principal.id,
                    source_thread_id=None,
                    title=new.title.strip(),
                    original_prompt=new.task.strip(),
                    task=new.task.strip(),
                    **rule_columns(rule),
                    delivery=new.delivery.value,
                    delivery_target=_target_for(new.delivery, new.delivery_target),
                    status=ScheduleStatus.ACTIVE.value,
                    next_run_at=first,
                    created_at=now,
                    updated_at=now,
                )
            )
            return task, 0

    async def update(
        self, principal: Principal, task_id: uuid.UUID, changes: ScheduleChanges
    ) -> tuple[ScheduledTask, int]:
        """Edit a schedule. A changed rule moves the next run to the rule's first slot
        after now; editing a finished one-time schedule to a future time makes it active
        again. A cancelled schedule cannot be changed."""
        now = self._clock()
        if changes.delivery is not None:
            await self._require_deliverable(principal, changes.delivery)
        async with transaction(self._session_factory) as session:
            schedules = ScheduleRepository(session)
            task = await _existing(schedules, principal, task_id, for_update=True)
            status = ScheduleStatus(task.status)
            if status is ScheduleStatus.CANCELLED:
                if changes == ScheduleChanges(status=ScheduleStatus.CANCELLED):
                    return task, await schedules.run_count(task.id)
                raise InvalidScheduleError("A cancelled schedule cannot be changed.")

            if changes.title is not None:
                task.title = changes.title
            if changes.task is not None:
                task.task = changes.task
            if changes.delivery is not None:
                task.delivery = changes.delivery.value
            if changes.delivery_target_given:
                task.delivery_target = changes.delivery_target
            task.delivery_target = _target_for(
                ScheduleDelivery(task.delivery), task.delivery_target
            )

            if changes.rule is not None:
                rule = changes.rule.apply_to(rule_of(task)).build(now)
                for column, value in rule_columns(rule).items():
                    setattr(task, column, value)
                if status is ScheduleStatus.PAUSED:
                    task.next_run_at = rule.next_after(now)
                else:
                    task.next_run_at = _first_slot(rule, now)
                    task.status = ScheduleStatus.ACTIVE.value

            if changes.status is not None:
                _change_status(task, changes.status, now)
            task.updated_at = now
            return task, await schedules.run_count(task.id)

    async def set_status(
        self, principal: Principal, task_id: uuid.UUID, status: ScheduleStatus
    ) -> tuple[ScheduledTask, int]:
        """Pause, resume, or cancel. Cancelling is final."""
        return await self.update(principal, task_id, ScheduleChanges(status=status))

    async def delete(self, principal: Principal, task_id: uuid.UUID) -> None:
        """Delete a schedule and its run history. Messages its runs posted stay in chat.
        Refused while a run is going: it would finish into a schedule that no longer
        exists."""
        async with transaction(self._session_factory) as session:
            schedules = ScheduleRepository(session)
            task = await _existing(schedules, principal, task_id, for_update=True)
            if await schedules.has_running_run(task.id):
                raise ScheduleRunInProgressError
            await schedules.delete(task)

    async def activity(
        self, principal: Principal, *, limit: int, offset: int
    ) -> tuple[list[ActivityEntry], int]:
        """Finished runs of the user's schedules, newest first."""
        async with self._session_factory() as session:
            rows, total = await ScheduleRepository(session).finished_runs_for_user(
                principal.id, limit=limit, offset=offset
            )
        return [
            ActivityEntry(run=run, task=task, thread_id=thread) for run, task, thread in rows
        ], total

    async def start_manual_run(self, principal: Principal, task_id: uuid.UUID) -> ScheduledTaskRun:
        """Run a schedule now, in the background. Its next scheduled slot is unchanged."""
        now = self._clock()
        async with transaction(self._session_factory) as session:
            schedules = ScheduleRepository(session)
            task = await _existing(schedules, principal, task_id, for_update=True)
            if task.status == ScheduleStatus.CANCELLED.value:
                raise InvalidScheduleError("A cancelled schedule cannot be run.")
            run = ScheduledTaskRun(
                id=new_uuid(),
                scheduled_task_id=task.id,
                trigger=ScheduleRunTrigger.MANUAL.value,
                status=ScheduleRunStatus.RUNNING.value,
                started_at=now,
                created_at=now,
            )
            if not await schedules.try_add_run(run):
                raise ScheduleRunInProgressError
        self._background.spawn(self._runner.execute(run.id), name=f"schedule-run-{run.id}")
        return run

    async def list_runs(
        self, principal: Principal, task_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[ScheduledTaskRun], int]:
        async with self._session_factory() as session:
            schedules = ScheduleRepository(session)
            await _existing(schedules, principal, task_id)
            return await schedules.list_runs(task_id, limit=limit, offset=offset)

    async def get_run(
        self, principal: Principal, task_id: uuid.UUID, run_id: uuid.UUID
    ) -> ScheduledTaskRun:
        async with self._session_factory() as session:
            schedules = ScheduleRepository(session)
            await _existing(schedules, principal, task_id)
            run = await schedules.get_run(task_id, run_id)
        if run is None:
            raise RecordNotFoundError("Schedule run", str(run_id))
        return run

    async def _require_deliverable(self, principal: Principal, delivery: ScheduleDelivery) -> None:
        """Results can go to chat, or to an app the user has connected."""
        app = DELIVERY_TOOLKITS.get(delivery)
        if app is None or app in await self._connections.last_connected(principal):
            return
        spec = find_tool(app)
        name = spec.name if spec is not None else app
        raise InvalidScheduleError(
            f"Connect {name} in Tools & Connections before sending results there."
        )


def _change_status(task: ScheduledTask, status: ScheduleStatus, now: datetime) -> None:
    """Pause, resume, or cancel. Resuming schedules the next slot from now, so slots
    missed while paused are skipped rather than run in a burst; a one-time schedule whose
    moment has passed cannot resume until its date is edited."""
    current = ScheduleStatus(task.status)
    if status is current:
        return
    if status is ScheduleStatus.ACTIVE:
        upcoming = rule_of(task).next_after(now)
        if upcoming is None:
            raise InvalidScheduleError(
                "This one-time schedule's time has passed. Change its date to run it again."
            )
        task.next_run_at = upcoming
    elif status is ScheduleStatus.CANCELLED:
        task.next_run_at = None
    elif status is ScheduleStatus.PAUSED and current is ScheduleStatus.COMPLETED:
        raise InvalidScheduleError("A completed schedule cannot be paused.")
    elif status is ScheduleStatus.COMPLETED:
        raise InvalidScheduleError("A schedule completes on its own after its last run.")
    task.status = status.value


def _first_slot(rule: ScheduleRule, now: datetime) -> datetime:
    upcoming = rule.next_after(now)
    if upcoming is None:
        raise InvalidScheduleError(PAST_SLOT_MESSAGE)
    return upcoming


def _target_for(delivery: ScheduleDelivery, target: str | None) -> str | None:
    """Chat has no target; an app's target is kept as given."""
    return None if delivery is ScheduleDelivery.CHAT else target


def _changed[T](new: T | None, current: T | None, kept: bool) -> T | None:
    if new is not None:
        return new
    return current if kept else None


async def _existing(
    schedules: ScheduleRepository,
    principal: Principal,
    task_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> ScheduledTask:
    task = await schedules.get(principal.id, task_id, for_update=for_update)
    if task is None:
        raise RecordNotFoundError("Schedule", str(task_id))
    return task
