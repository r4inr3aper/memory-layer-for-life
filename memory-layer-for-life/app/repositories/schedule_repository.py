import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.domain.enums import ScheduleRunStatus, ScheduleStatus
from app.models.chat_message import ChatMessage
from app.models.scheduled_task import ScheduledTask
from app.models.scheduled_task_run import ScheduledTaskRun
from app.repositories.base import BaseRepository


class ScheduleRepository(BaseRepository):
    """Persistence of scheduled tasks and their runs."""

    # --- Tasks -------------------------------------------------------------------------

    async def add(self, task: ScheduledTask) -> ScheduledTask:
        self._session.add(task)
        await self._session.flush()
        return task

    async def get(
        self, user_id: uuid.UUID, task_id: uuid.UUID, *, for_update: bool = False
    ) -> ScheduledTask | None:
        """A task of this user. Another user's task reads as missing."""
        query = select(ScheduledTask).where(
            ScheduledTask.id == task_id, ScheduledTask.user_id == user_id
        )
        if for_update:
            query = query.with_for_update()
        result: ScheduledTask | None = await self._session.scalar(query)
        return result

    async def get_by_id(self, task_id: uuid.UUID) -> ScheduledTask | None:
        """For background work that acts on a run, never for serving a request."""
        return await self._session.get(ScheduledTask, task_id)

    async def delete(self, task: ScheduledTask) -> None:
        """Delete the task; its runs go with it. Messages it delivered stay in their chat."""
        await self._session.delete(task)
        await self._session.flush()

    async def has_running_run(self, task_id: uuid.UUID) -> bool:
        running = await self._session.scalar(
            select(func.count())
            .select_from(ScheduledTaskRun)
            .where(
                ScheduledTaskRun.scheduled_task_id == task_id,
                ScheduledTaskRun.status == ScheduleRunStatus.RUNNING.value,
            )
        )
        return bool(running)

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[tuple[ScheduledTask, int]], int]:
        """Tasks newest first, each with its number of runs (skipped slots not counted),
        and the total count."""
        total = await self._session.scalar(
            select(func.count()).select_from(ScheduledTask).where(ScheduledTask.user_id == user_id)
        )
        run_counts = (
            select(
                ScheduledTaskRun.scheduled_task_id,
                func.count().label("run_count"),
            )
            .where(ScheduledTaskRun.status != ScheduleRunStatus.SKIPPED.value)
            .group_by(ScheduledTaskRun.scheduled_task_id)
            .subquery()
        )
        rows = await self._session.execute(
            select(ScheduledTask, func.coalesce(run_counts.c.run_count, 0))
            .outerjoin(run_counts, run_counts.c.scheduled_task_id == ScheduledTask.id)
            .where(ScheduledTask.user_id == user_id)
            .order_by(ScheduledTask.created_at.desc(), ScheduledTask.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [(task, int(count)) for task, count in rows.tuples()], int(total or 0)

    async def run_count(self, task_id: uuid.UUID) -> int:
        """Runs that happened; skipped slots are not counted."""
        total = await self._session.scalar(
            select(func.count())
            .select_from(ScheduledTaskRun)
            .where(
                ScheduledTaskRun.scheduled_task_id == task_id,
                ScheduledTaskRun.status != ScheduleRunStatus.SKIPPED.value,
            )
        )
        return int(total or 0)

    async def claim_due(self, now: datetime, *, limit: int) -> list[ScheduledTask]:
        """Lock active tasks whose next slot has come, oldest slot first.

        ``SKIP LOCKED`` lets concurrent dispatchers take disjoint sets. The caller moves
        each task's ``next_run_at`` on before its transaction commits.
        """
        rows = await self._session.scalars(
            select(ScheduledTask)
            .where(
                ScheduledTask.status == ScheduleStatus.ACTIVE.value,
                ScheduledTask.next_run_at <= now,
            )
            .order_by(ScheduledTask.next_run_at, ScheduledTask.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(rows)

    async def next_due_at(self) -> datetime | None:
        """When the earliest active schedule's next slot is."""
        result: datetime | None = await self._session.scalar(
            select(func.min(ScheduledTask.next_run_at)).where(
                ScheduledTask.status == ScheduleStatus.ACTIVE.value
            )
        )
        return result

    # --- Runs --------------------------------------------------------------------------

    async def try_add_run(self, run: ScheduledTaskRun) -> bool:
        """Insert a run unless the slot was taken or the task is already running.

        The unique indexes decide, so the answer holds under concurrency. A savepoint keeps
        the caller's transaction usable after a refusal.
        """
        try:
            async with self._session.begin_nested():
                self._session.add(run)
                await self._session.flush()
        except IntegrityError:
            return False
        return True

    async def get_run(self, task_id: uuid.UUID, run_id: uuid.UUID) -> ScheduledTaskRun | None:
        result: ScheduledTaskRun | None = await self._session.scalar(
            select(ScheduledTaskRun).where(
                ScheduledTaskRun.id == run_id, ScheduledTaskRun.scheduled_task_id == task_id
            )
        )
        return result

    async def get_run_by_id(
        self, run_id: uuid.UUID, *, for_update: bool = False
    ) -> ScheduledTaskRun | None:
        query = select(ScheduledTaskRun).where(ScheduledTaskRun.id == run_id)
        if for_update:
            query = query.with_for_update()
        result: ScheduledTaskRun | None = await self._session.scalar(query)
        return result

    async def list_runs(
        self, task_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[ScheduledTaskRun], int]:
        """Runs of a task, newest first."""
        total = await self.run_count(task_id)
        rows = await self._session.scalars(
            select(ScheduledTaskRun)
            .where(ScheduledTaskRun.scheduled_task_id == task_id)
            .order_by(ScheduledTaskRun.started_at.desc(), ScheduledTaskRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), total

    async def lock_stale_runs(self, started_before: datetime) -> list[ScheduledTaskRun]:
        """Runs still marked running that started before the cutoff."""
        rows = await self._session.scalars(
            select(ScheduledTaskRun)
            .where(
                ScheduledTaskRun.status == ScheduleRunStatus.RUNNING.value,
                ScheduledTaskRun.started_at < started_before,
            )
            .with_for_update(skip_locked=True)
        )
        return list(rows)

    async def finished_runs_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[tuple[ScheduledTaskRun, ScheduledTask, uuid.UUID | None]], int]:
        """Finished runs of the user's schedules, newest first, each with its schedule and
        the thread its result was posted to, if it went to chat. Skipped slots have no
        result, so they are left out; a schedule's own history shows them."""
        finished = [
            ScheduledTask.user_id == user_id,
            ScheduledTaskRun.status.in_(
                [ScheduleRunStatus.SUCCEEDED.value, ScheduleRunStatus.FAILED.value]
            ),
        ]
        total = await self._session.scalar(
            select(func.count())
            .select_from(ScheduledTaskRun)
            .join(ScheduledTask, ScheduledTask.id == ScheduledTaskRun.scheduled_task_id)
            .where(*finished)
        )
        message = aliased(ChatMessage)
        rows = await self._session.execute(
            select(ScheduledTaskRun, ScheduledTask, message.thread_id)
            .join(ScheduledTask, ScheduledTask.id == ScheduledTaskRun.scheduled_task_id)
            .outerjoin(message, message.id == ScheduledTaskRun.chat_message_id)
            .where(*finished)
            .order_by(ScheduledTaskRun.finished_at.desc(), ScheduledTaskRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [(run, task, thread_id) for run, task, thread_id in rows.tuples()], int(total or 0)
