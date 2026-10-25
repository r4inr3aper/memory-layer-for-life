"""Executing scheduled tasks.

``ScheduleDispatcher.run_due`` claims due slots and executes them; ``ScheduleLoop``
calls it periodically inside the API process, and ``scripts/run_schedules.py`` can run
it on its own.

Claiming is one transaction: due tasks are locked with ``SKIP LOCKED``, each gets a run
row for its slot, and its ``next_run_at`` moves to the first slot after now (a one-time
task then has none and is completed). The slot's unique index makes a slot run at most
once even with several dispatchers. Slots missed while nothing was dispatching are not
made up: a task runs once and continues on schedule. A slot found more than the grace
period late (``SCHEDULE_MISSED_GRACE_SECONDS``, at most half an interval schedule's
period) is skipped rather than run, since a morning brief at night helps nobody; a slot
due while an earlier run of the task is still going is skipped too. Skipped slots get a
run row with the reason, so the history shows them.

A run is never retried. It may already have sent a message, and sending it twice is
worse than reporting that it failed. A run whose process stopped is marked interrupted
by the next dispatcher pass.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import (
    ChatRole,
    LlmCallOrigin,
    LlmOperation,
    ScheduleDelivery,
    ScheduleFrequency,
    ScheduleRunStatus,
    ScheduleRunTrigger,
    ScheduleStatus,
    Weekday,
)
from app.domain.errors import (
    DomainError,
    IntegrationNotConfiguredError,
    ProviderNotConfiguredError,
    ScheduleDeliveryError,
    ScheduleRunInterruptedError,
    ScheduleSlotBusyError,
    ScheduleSlotMissedError,
)
from app.domain.principal import Principal
from app.domain.schedule_rules import ScheduleRule
from app.domain.tool_catalog import find_tool
from app.integrations.assistant.base import AssistantModel, UserText
from app.integrations.composio import SERVICE_NAME as COMPOSIO
from app.integrations.llm_calls import LlmCallContext
from app.models.chat_message import ChatMessage
from app.models.scheduled_task import ScheduledTask
from app.models.scheduled_task_run import ScheduledTaskRun
from app.repositories.chat_repository import ChatRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.repositories.user_repository import UserRepository
from app.schemas.message_metadata import MessageMetadata, ScheduledRunNote
from app.services.assistant.agent import AssistantAgent
from app.services.assistant.context import TurnContext, WritePolicy
from app.services.assistant.prompts import scheduled_context, scheduled_instructions
from app.services.assistant.tools import AssistantToolbox, changes_data, delivery_app
from app.services.chat import MAIN_THREAD_TITLE, append_message
from app.services.notifications import PushService, RunNotice
from app.services.pacing import ALWAYS_ON, BackgroundPacer
from app.services.tool_connections import ToolConnectionService
from app.services.usage import UsageService

logger = structlog.get_logger(__name__)

UNEXPECTED_ERROR_CODE: Final = "UNEXPECTED_ERROR"
_MAX_SUMMARY_CHARS: Final = 4000


def rule_of(task: ScheduledTask) -> ScheduleRule:
    return ScheduleRule(
        frequency=ScheduleFrequency(task.frequency),
        local_time=task.local_time,
        timezone_name=task.timezone,
        weekdays=tuple(Weekday(day) for day in task.weekdays or ()),
        day_of_month=task.day_of_month,
        start_date=task.start_date,
        interval_hours=task.interval_hours,
    )


def rule_columns(rule: ScheduleRule) -> dict[str, object]:
    """A task's column values for the rule, with the fields its frequency does not use
    cleared."""
    return {
        "frequency": rule.frequency.value,
        "local_time": rule.local_time,
        "weekdays": [day.value for day in rule.weekdays] or None,
        "day_of_month": rule.day_of_month,
        "start_date": rule.start_date,
        "interval_hours": rule.interval_hours,
        "timezone": rule.timezone_name,
    }


@dataclass(frozen=True, slots=True)
class _TaskSnapshot:
    """What a run needs from its task, read once so no session stays open meanwhile."""

    task_id: uuid.UUID
    principal: Principal
    title: str
    original_prompt: str
    task: str
    timezone: str
    delivery: ScheduleDelivery
    delivery_target: str | None
    assistant_name: str | None


@dataclass(frozen=True, slots=True)
class _Outcome:
    summary: str | None
    error: DomainError | None = None


class ScheduleRunner:
    """Executes one claimed run and records how it ended."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        model: AssistantModel | None,
        toolbox: AssistantToolbox,
        connections: ToolConnectionService,
        usage: UsageService,
        push: PushService,
        max_steps: int,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._agent = AssistantAgent(model, max_steps=max_steps) if model is not None else None
        self._toolbox = toolbox
        self._connections = connections
        self._usage = usage
        self._push = push
        self._clock = clock

    async def execute(self, run_id: uuid.UUID) -> None:
        snapshot = await self._snapshot(run_id)
        if snapshot is None:
            return
        log = logger.bind(run_id=str(run_id), scheduled_task_id=str(snapshot.task_id))
        try:
            outcome = await self._perform(snapshot)
        except asyncio.CancelledError:
            await asyncio.shield(
                self._finish(run_id, _Outcome(summary=None, error=ScheduleRunInterruptedError()))
            )
            raise
        except DomainError as error:
            outcome = _Outcome(summary=None, error=error)
        except Exception:
            log.exception("schedule_run_crashed")
            outcome = _Outcome(
                summary=None,
                error=_UnexpectedRunError("The run failed unexpectedly."),
            )
        notice = await self._finish(run_id, outcome)
        if notice is not None:
            await self._push.notify_run_finished(notice)
        if outcome.error is None:
            log.info("schedule_run_succeeded")
        else:
            log.warning("schedule_run_failed", error_code=outcome.error.code)

    async def _snapshot(self, run_id: uuid.UUID) -> _TaskSnapshot | None:
        async with self._session_factory() as session:
            schedules = ScheduleRepository(session)
            run = await schedules.get_run_by_id(run_id)
            if run is None or run.status != ScheduleRunStatus.RUNNING.value:
                return None
            task = await schedules.get_by_id(run.scheduled_task_id)
            if task is None:  # pragma: no cover - runs cascade with their task
                return None
            user = await UserRepository(session).get(task.user_id)
            return _TaskSnapshot(
                task_id=task.id,
                principal=Principal(
                    id=task.user_id,
                    email=user.email if user is not None else None,
                    display_name=user.display_name if user is not None else None,
                ),
                title=task.title,
                original_prompt=task.original_prompt,
                task=task.task,
                timezone=task.timezone,
                delivery=ScheduleDelivery(task.delivery),
                delivery_target=task.delivery_target,
                assistant_name=user.assistant_name if user is not None else None,
            )

    async def _perform(self, snapshot: _TaskSnapshot) -> _Outcome:
        agent = self._agent
        if agent is None:
            raise ProviderNotConfiguredError
        app = delivery_app(snapshot.delivery)
        spec = find_tool(app) if app is not None else None
        accounts: dict[str, list[str]] | None = None
        if app is not None:
            if not self._connections.available:
                raise IntegrationNotConfiguredError(COMPOSIO, "COMPOSIO_API_KEY")
            accounts = await self._connections.active_accounts(snapshot.principal)
            if app not in accounts:
                name = spec.name if spec is not None else app
                raise ScheduleDeliveryError(f"Connect {name} so this schedule can deliver to it.")
            connected = sorted(accounts)
        else:
            # A chat delivery may still read the user's apps, for example to summarize their
            # email. Use what chat turns use: the connections as last seen. The app tools
            # look the accounts up from Composio when they are called.
            connected = await self._connections.last_connected(snapshot.principal)
        # Counted only once the run can go ahead: a run refused above used nothing.
        async with transaction(self._session_factory) as session:
            await self._usage.count_scheduled_run(
                session, snapshot.principal.id, timezone_name=snapshot.timezone
            )

        turn = TurnContext(
            principal=snapshot.principal,
            timezone_name=snapshot.timezone,
            original_prompt=snapshot.original_prompt,
            allow_proposals=False,
            write_policy=WritePolicy.DELIVERY_APP_ONLY,
            delivery_app=app,
            active_accounts=accounts,
        )
        result = await agent.run(
            instructions=scheduled_instructions(self._toolbox.capabilities),
            context=scheduled_context(
                now=self._clock(),
                timezone_name=snapshot.timezone,
                title=snapshot.title,
                delivery_name=spec.name if spec is not None else "chat",
                delivery_target=snapshot.delivery_target,
                assistant_name=snapshot.assistant_name,
                connected_apps=sorted(
                    tool.name for slug in connected if (tool := find_tool(slug)) is not None
                ),
            ),
            history=[UserText(snapshot.task)],
            tools=self._toolbox.for_schedule(),
            turn=turn,
            operation=LlmOperation.SCHEDULED_TASK,
            call_context=LlmCallContext(
                origin=LlmCallOrigin.SCHEDULER, user_id=snapshot.principal.id
            ),
        )
        summary = result.text[:_MAX_SUMMARY_CHARS] or None
        if app is not None and not any(
            executed_app == app and changes_data(slug) for executed_app, slug in turn.executed
        ):
            name = spec.name if spec is not None else app
            return _Outcome(
                summary=summary,
                error=ScheduleDeliveryError(f"The result was not delivered to {name}."),
            )
        if not result.completed:
            return _Outcome(
                summary=summary,
                error=_UnexpectedRunError("The run needed more steps than allowed."),
            )
        return _Outcome(summary=summary)

    async def _finish(self, run_id: uuid.UUID, outcome: _Outcome) -> RunNotice | None:
        """Record how the run ended. Returns what to notify the user about, or None when
        another process already finished the run."""
        now = self._clock()
        async with transaction(self._session_factory) as session:
            schedules = ScheduleRepository(session)
            run = await schedules.get_run_by_id(run_id, for_update=True)
            if run is None or run.status != ScheduleRunStatus.RUNNING.value:
                return None
            task = await schedules.get_by_id(run.scheduled_task_id)
            if task is None:  # pragma: no cover - runs cascade with their task
                return None
            error = outcome.error
            run.status = (
                ScheduleRunStatus.FAILED.value if error else ScheduleRunStatus.SUCCEEDED.value
            )
            run.finished_at = now
            run.summary = outcome.summary
            run.error_code = error.code if error else None
            run.error_message = error.message if error else None
            thread_id = None
            if task.delivery == ScheduleDelivery.CHAT.value:
                delivered = await _deliver_to_chat(session, task, run, now)
                run.chat_message_id = delivered.id
                thread_id = delivered.thread_id
            record_last_run(task, run)
            return RunNotice(
                user_id=task.user_id,
                scheduled_task_id=task.id,
                run_id=run.id,
                title=task.title,
                succeeded=error is None,
                text=run.summary if error is None else run.error_message,
                thread_id=thread_id,
            )


class _UnexpectedRunError(DomainError):
    code = UNEXPECTED_ERROR_CODE


def record_last_run(task: ScheduledTask, run: ScheduledTaskRun) -> None:
    task.last_run_at = run.finished_at
    task.last_run_status = run.status
    task.last_run_summary = run.summary
    task.last_run_error = run.error_message


async def _deliver_to_chat(
    session: AsyncSession, task: ScheduledTask, run: ScheduledTaskRun, now: datetime
) -> ChatMessage:
    """Post the run's result to the thread the schedule came from, or the main thread."""
    chat = ChatRepository(session)
    thread = None
    if task.source_thread_id is not None:
        thread = await chat.get_thread(task.user_id, task.source_thread_id, for_update=True)
    if thread is None:
        thread = await chat.ensure_main_thread(task.user_id, title=MAIN_THREAD_TITLE, now=now)
    if run.status == ScheduleRunStatus.SUCCEEDED.value:
        content = f"Scheduled task complete: {task.title}"
        if run.summary:
            content = f"{content}\n\n{run.summary}"
    else:
        content = f"Scheduled task failed: {task.title}\n\n{run.error_message}"
    message = await append_message(
        chat,
        thread,
        role=ChatRole.ASSISTANT,
        content=content,
        metadata=MessageMetadata(
            scheduled_run=ScheduledRunNote(
                scheduled_task_id=task.id,
                run_id=run.id,
                status=ScheduleRunStatus(run.status),
            )
        ),
        now=now,
    )
    return message


class ScheduleDispatcher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: ScheduleRunner,
        *,
        batch_size: int,
        concurrency: int,
        stale_after: timedelta,
        missed_grace: timedelta,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._batch_size = batch_size
        self._concurrency = concurrency
        self._stale_after = stale_after
        self._missed_grace = missed_grace
        self._clock = clock

    async def next_due(self) -> datetime | None:
        """When the next schedule slot falls due."""
        async with self._session_factory() as session:
            return await ScheduleRepository(session).next_due_at()

    async def run_due(self) -> list[uuid.UUID]:
        """Claim due slots, execute them, and return the ids of the runs executed."""
        claimed = await self._claim()
        if claimed:
            semaphore = asyncio.Semaphore(self._concurrency)

            async def execute(run_id: uuid.UUID) -> None:
                async with semaphore:
                    await self._runner.execute(run_id)

            await asyncio.gather(*(execute(run_id) for run_id in claimed))
        return claimed

    async def _claim(self) -> list[uuid.UUID]:
        now = self._clock()
        claimed: list[uuid.UUID] = []
        async with transaction(self._session_factory) as session:
            schedules = ScheduleRepository(session)
            await self._mark_interrupted(schedules, now)
            for task in await schedules.claim_due(now, limit=self._batch_size):
                slot = task.next_run_at
                if slot is None:  # pragma: no cover - active tasks always have a slot
                    continue
                rule = rule_of(task)
                task.next_run_at = rule.next_after(max(now, slot))
                if task.next_run_at is None:
                    task.status = ScheduleStatus.COMPLETED.value
                if now - slot > self._grace_for(rule):
                    await self._skip(schedules, task, slot, now, ScheduleSlotMissedError())
                    continue
                run = ScheduledTaskRun(
                    id=new_uuid(),
                    scheduled_task_id=task.id,
                    trigger=ScheduleRunTrigger.SCHEDULE.value,
                    status=ScheduleRunStatus.RUNNING.value,
                    scheduled_for=slot,
                    started_at=now,
                    created_at=now,
                )
                if await schedules.try_add_run(run):
                    claimed.append(run.id)
                else:
                    # An earlier run is still going, or the slot ran already (then nothing
                    # is recorded: the slot keeps its run).
                    await self._skip(schedules, task, slot, now, ScheduleSlotBusyError())
        return claimed

    def _grace_for(self, rule: ScheduleRule) -> timedelta:
        """How late a slot may still run. At most half an interval, so a late run never
        lands on top of the next one."""
        interval = rule.interval
        return min(self._missed_grace, interval / 2) if interval is not None else self._missed_grace

    async def _skip(
        self,
        schedules: ScheduleRepository,
        task: ScheduledTask,
        slot: datetime,
        now: datetime,
        reason: DomainError,
    ) -> None:
        """Record a slot that is not run, with the reason, so the history shows it."""
        run = ScheduledTaskRun(
            id=new_uuid(),
            scheduled_task_id=task.id,
            trigger=ScheduleRunTrigger.SCHEDULE.value,
            status=ScheduleRunStatus.SKIPPED.value,
            scheduled_for=slot,
            started_at=now,
            finished_at=now,
            error_code=reason.code,
            error_message=reason.message,
            created_at=now,
        )
        if await schedules.try_add_run(run):
            record_last_run(task, run)
            logger.info("schedule_slot_skipped", scheduled_task_id=str(task.id), reason=reason.code)

    async def _mark_interrupted(self, schedules: ScheduleRepository, now: datetime) -> None:
        error = ScheduleRunInterruptedError()
        for run in await schedules.lock_stale_runs(now - self._stale_after):
            run.status = ScheduleRunStatus.FAILED.value
            run.finished_at = now
            run.error_code = error.code
            run.error_message = error.message
            task = await schedules.get_by_id(run.scheduled_task_id)
            if task is not None:
                record_last_run(task, run)
            logger.warning("schedule_run_interrupted", run_id=str(run.id))


class ScheduleLoop:
    """Calls the dispatcher every ``interval_seconds`` while the API runs, or as the
    pacer allows when the database should sleep (``app.services.pacing``)."""

    def __init__(
        self,
        dispatcher: ScheduleDispatcher,
        *,
        interval_seconds: float,
        pacer: BackgroundPacer = ALWAYS_ON,
    ) -> None:
        self._dispatcher = dispatcher
        self._interval_seconds = interval_seconds
        self._pacer = pacer
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="schedule-loop")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self._dispatcher.run_due()
            except Exception:
                # A failed pass must not end the loop; the next pass tries again.
                logger.exception("schedule_dispatch_failed")
            next_due = await self._pacer.next_due(self._dispatcher.next_due, loop="schedule")
            await self._pacer.sleep(self._interval_seconds, next_due=next_due)
