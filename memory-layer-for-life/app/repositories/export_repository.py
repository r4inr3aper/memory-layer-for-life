"""Everything the app holds for one user, read for a data export."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.app_user import AppUser
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.models.daily_usage import DailyUsage
from app.models.entity import Entity
from app.models.memory import Memory
from app.models.memory_entity import MemoryEntity
from app.models.memory_source import MemorySource
from app.models.scheduled_task import ScheduledTask
from app.models.scheduled_task_run import ScheduledTaskRun
from app.models.tool_connection import ToolConnection
from app.repositories.base import BaseRepository


class ExportRepository(BaseRepository):
    async def user(self, user_id: uuid.UUID) -> AppUser | None:
        return await self._session.get(AppUser, user_id)

    async def memories(self, owner_id: uuid.UUID) -> list[Memory]:
        """Every memory, whatever its status, with its evidence and entities, oldest first."""
        rows = await self._session.scalars(
            select(Memory)
            .where(Memory.owner_id == owner_id)
            .options(
                selectinload(Memory.sources).joinedload(MemorySource.raw_message),
                selectinload(Memory.memory_entities).joinedload(MemoryEntity.entity),
            )
            .order_by(Memory.created_at, Memory.id)
        )
        return list(rows)

    async def entities(self, owner_id: uuid.UUID) -> list[Entity]:
        rows = await self._session.scalars(
            select(Entity).where(Entity.owner_id == owner_id).order_by(Entity.created_at, Entity.id)
        )
        return list(rows)

    async def threads(self, user_id: uuid.UUID) -> list[ChatThread]:
        rows = await self._session.scalars(
            select(ChatThread)
            .where(ChatThread.user_id == user_id)
            .order_by(ChatThread.created_at, ChatThread.id)
        )
        return list(rows)

    async def messages(self, user_id: uuid.UUID) -> list[ChatMessage]:
        rows = await self._session.scalars(
            select(ChatMessage)
            .join(ChatThread, ChatThread.id == ChatMessage.thread_id)
            .where(ChatThread.user_id == user_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
        return list(rows)

    async def schedules(self, user_id: uuid.UUID) -> list[ScheduledTask]:
        rows = await self._session.scalars(
            select(ScheduledTask)
            .where(ScheduledTask.user_id == user_id)
            .order_by(ScheduledTask.created_at, ScheduledTask.id)
        )
        return list(rows)

    async def schedule_runs(self, user_id: uuid.UUID) -> list[ScheduledTaskRun]:
        rows = await self._session.scalars(
            select(ScheduledTaskRun)
            .join(ScheduledTask, ScheduledTask.id == ScheduledTaskRun.scheduled_task_id)
            .where(ScheduledTask.user_id == user_id)
            .order_by(ScheduledTaskRun.started_at, ScheduledTaskRun.id)
        )
        return list(rows)

    async def connections(self, user_id: uuid.UUID) -> list[ToolConnection]:
        rows = await self._session.scalars(
            select(ToolConnection)
            .where(ToolConnection.user_id == user_id)
            .order_by(ToolConnection.toolkit_slug)
        )
        return list(rows)

    async def usage(self, user_id: uuid.UUID) -> list[DailyUsage]:
        rows = await self._session.scalars(
            select(DailyUsage).where(DailyUsage.user_id == user_id).order_by(DailyUsage.day)
        )
        return list(rows)
