import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Date, DateTime, Label, cast, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import InstrumentedAttribute

from app.db.base import new_uuid
from app.domain.enums import UsageGranularity
from app.models.app_user import AppUser
from app.models.daily_usage import DailyUsage
from app.models.llm_call import LlmCall
from app.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal | None


class UsageRepository(BaseRepository):
    """Counts what a user has used, for the daily limit and the usage meter."""

    async def prompt_limit_of(self, user_id: uuid.UUID) -> int | None:
        """The user's own daily limit, or None when the default applies."""
        limit: int | None = await self._session.scalar(
            select(AppUser.daily_prompt_limit).where(AppUser.id == user_id)
        )
        return limit

    async def day(self, user_id: uuid.UUID, day: date) -> DailyUsage | None:
        found: DailyUsage | None = await self._session.scalar(
            select(DailyUsage).where(DailyUsage.user_id == user_id, DailyUsage.day == day)
        )
        return found

    async def count_chat_message(
        self, user_id: uuid.UUID, day: date, *, limit: int | None, now: datetime
    ) -> bool:
        return await self._count(DailyUsage.chat_messages, user_id, day, limit=limit, now=now)

    async def count_scheduled_run(
        self, user_id: uuid.UUID, day: date, *, limit: int | None, now: datetime
    ) -> bool:
        return await self._count(DailyUsage.scheduled_runs, user_id, day, limit=limit, now=now)

    async def _count(
        self,
        column: InstrumentedAttribute[int],
        user_id: uuid.UUID,
        day: date,
        *,
        limit: int | None,
        now: datetime,
    ) -> bool:
        """Add one prompt to the user's day unless the day already holds ``limit``
        (None: no limit). Returns whether it was added.

        One statement, so concurrent requests cannot both take the last prompt. The first
        prompt of a day is always added; a limit is at least 1.
        """
        statement = insert(DailyUsage).values(
            id=new_uuid(),
            user_id=user_id,
            day=day,
            chat_messages=1 if column is DailyUsage.chat_messages else 0,
            scheduled_runs=1 if column is DailyUsage.scheduled_runs else 0,
            created_at=now,
            updated_at=now,
        )
        upsert = statement.on_conflict_do_update(
            index_elements=[DailyUsage.user_id, DailyUsage.day],
            set_={column.key: column + 1, "updated_at": now},
            where=(
                DailyUsage.chat_messages + DailyUsage.scheduled_runs < limit
                if limit is not None
                else None
            ),
        ).returning(DailyUsage.id)
        return (await self._session.execute(upsert)).first() is not None

    async def prompts_by_period(
        self, user_id: uuid.UUID, granularity: UsageGranularity, since: date
    ) -> dict[date, int]:
        """Prompts per period from ``since`` on, keyed by each period's first day."""
        bucket = _period_start(granularity, cast(DailyUsage.day, DateTime))
        rows = await self._session.execute(
            select(bucket, func.sum(DailyUsage.chat_messages + DailyUsage.scheduled_runs))
            .where(DailyUsage.user_id == user_id, DailyUsage.day >= since)
            .group_by(bucket)
        )
        return {row[0]: int(row[1] or 0) for row in rows}

    async def model_usage_by_period(
        self, user_id: uuid.UUID, granularity: UsageGranularity, since: date
    ) -> dict[date, ModelUsage]:
        """Model calls made for the user per period from ``since`` on, keyed by each
        period's first day."""
        bucket = _period_start(granularity, func.timezone("UTC", LlmCall.started_at))
        rows = await self._session.execute(
            select(
                bucket,
                func.coalesce(func.sum(LlmCall.input_tokens), 0),
                func.coalesce(func.sum(LlmCall.output_tokens), 0),
                func.sum(LlmCall.estimated_cost_usd),
            )
            .where(
                LlmCall.user_id == user_id,
                LlmCall.started_at >= datetime.combine(since, time(), tzinfo=UTC),
            )
            .group_by(bucket)
        )
        return {
            row[0]: ModelUsage(
                input_tokens=int(row[1]), output_tokens=int(row[2]), estimated_cost_usd=row[3]
            )
            for row in rows
        }

    async def model_usage_since(self, user_id: uuid.UUID, since: datetime) -> ModelUsage:
        row = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(LlmCall.input_tokens), 0),
                    func.coalesce(func.sum(LlmCall.output_tokens), 0),
                    func.sum(LlmCall.estimated_cost_usd),
                ).where(LlmCall.user_id == user_id, LlmCall.started_at >= since)
            )
        ).one()
        return ModelUsage(
            input_tokens=int(row[0]), output_tokens=int(row[1]), estimated_cost_usd=row[2]
        )


def _period_start(granularity: UsageGranularity, moment: ColumnElement[Any]) -> Label[date]:
    """The first day of the period a UTC timestamp falls in, as a date. The unit is
    written into the SQL rather than bound, so the grouped expression is identical in
    SELECT and GROUP BY; it comes from the enum, never from input."""
    unit: ColumnElement[str] = literal_column(f"'{granularity.value}'")
    return cast(func.date_trunc(unit, moment), Date).label("period_start")
