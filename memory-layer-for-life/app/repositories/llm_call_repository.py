import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Self

from sqlalchemy import case, func, select
from sqlalchemy.sql.elements import ColumnElement

from app.domain.enums import LlmCallOrigin, LlmCallStatus, LlmOperation
from app.models.llm_call import LlmCall
from app.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class LlmCallFilter:
    """Which calls to look at. Every field narrows the selection; ``None`` does not."""

    origin: LlmCallOrigin | None = None
    operation: LlmOperation | None = None
    status: LlmCallStatus | None = None
    model: str | None = None
    processing_run_id: uuid.UUID | None = None
    evaluation_run_id: uuid.UUID | None = None
    playground_run_id: uuid.UUID | None = None
    started_from: datetime | None = None
    started_before: datetime | None = None

    def conditions(self) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if self.origin is not None:
            conditions.append(LlmCall.origin == self.origin.value)
        if self.operation is not None:
            conditions.append(LlmCall.operation == self.operation.value)
        if self.status is not None:
            conditions.append(LlmCall.status == self.status.value)
        if self.model is not None:
            conditions.append(LlmCall.requested_model == self.model)
        if self.processing_run_id is not None:
            conditions.append(LlmCall.processing_run_id == self.processing_run_id)
        if self.evaluation_run_id is not None:
            conditions.append(LlmCall.evaluation_run_id == self.evaluation_run_id)
        if self.playground_run_id is not None:
            conditions.append(LlmCall.playground_run_id == self.playground_run_id)
        if self.started_from is not None:
            conditions.append(LlmCall.started_at >= self.started_from)
        if self.started_before is not None:
            conditions.append(LlmCall.started_at < self.started_before)
        return conditions


@dataclass(frozen=True, slots=True)
class UsageTotals:
    """Sums over a set of calls. Two totals can be added.

    ``estimated_cost_usd`` adds up the calls whose price is known. ``unpriced_calls``
    says how many are missing from it, so a total is never silently too low.
    """

    calls: int = 0
    failed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal(0)
    unpriced_calls: int = 0
    duration_ms: int = 0

    @property
    def average_duration_ms(self) -> float | None:
        return self.duration_ms / self.calls if self.calls else None

    def __add__(self, other: Self) -> Self:
        return type(self)(
            calls=self.calls + other.calls,
            failed_calls=self.failed_calls + other.failed_calls,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
            cache_creation_input_tokens=(
                self.cache_creation_input_tokens + other.cache_creation_input_tokens
            ),
            estimated_cost_usd=self.estimated_cost_usd + other.estimated_cost_usd,
            unpriced_calls=self.unpriced_calls + other.unpriced_calls,
            duration_ms=self.duration_ms + other.duration_ms,
        )


@dataclass(frozen=True, slots=True)
class DailyModelUsage:
    """Usage of one requested model on one local calendar day."""

    day: date
    model: str
    totals: UsageTotals


@dataclass(frozen=True, slots=True)
class OriginOperationUsage:
    origin: LlmCallOrigin
    operation: LlmOperation
    totals: UsageTotals


@dataclass(frozen=True, slots=True)
class LatencyPercentiles:
    p50_ms: float | None
    p95_ms: float | None


@dataclass(frozen=True, slots=True)
class ErrorCount:
    error_code: str
    calls: int
    last_seen_at: datetime


def _usage_columns() -> list[ColumnElement[Any]]:
    failed = case((LlmCall.status == LlmCallStatus.FAILED.value, 1), else_=0)
    unpriced = case((LlmCall.estimated_cost_usd.is_(None), 1), else_=0)
    return [
        func.count().label("calls"),
        func.coalesce(func.sum(failed), 0).label("failed_calls"),
        func.coalesce(func.sum(LlmCall.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(LlmCall.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(LlmCall.cache_read_input_tokens), 0).label(
            "cache_read_input_tokens"
        ),
        func.coalesce(func.sum(LlmCall.cache_creation_input_tokens), 0).label(
            "cache_creation_input_tokens"
        ),
        func.coalesce(func.sum(LlmCall.estimated_cost_usd), 0).label("estimated_cost_usd"),
        func.coalesce(func.sum(unpriced), 0).label("unpriced_calls"),
        func.coalesce(func.sum(LlmCall.duration_ms), 0).label("duration_ms"),
    ]


def _totals(row: Any) -> UsageTotals:
    return UsageTotals(
        calls=int(row.calls),
        failed_calls=int(row.failed_calls),
        input_tokens=int(row.input_tokens),
        output_tokens=int(row.output_tokens),
        cache_read_input_tokens=int(row.cache_read_input_tokens),
        cache_creation_input_tokens=int(row.cache_creation_input_tokens),
        estimated_cost_usd=Decimal(row.estimated_cost_usd),
        unpriced_calls=int(row.unpriced_calls),
        duration_ms=int(row.duration_ms),
    )


class LlmCallRepository(BaseRepository):
    """Persistence and aggregation of the model call log."""

    async def add(self, call: LlmCall) -> LlmCall:
        self._session.add(call)
        await self._session.flush()
        return call

    async def get(self, call_id: uuid.UUID) -> LlmCall | None:
        return await self._session.get(LlmCall, call_id)

    async def list_calls(
        self, selection: LlmCallFilter, *, limit: int, offset: int
    ) -> tuple[list[LlmCall], int]:
        """Page through calls, newest first. Returns the page and the total match count."""
        conditions = selection.conditions()
        total = await self._session.scalar(
            select(func.count()).select_from(LlmCall).where(*conditions)
        )
        rows = await self._session.scalars(
            select(LlmCall)
            .where(*conditions)
            .order_by(LlmCall.started_at.desc(), LlmCall.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def latest_for_playground_run(self, playground_run_id: uuid.UUID) -> LlmCall | None:
        rows = await self._session.scalars(
            select(LlmCall)
            .where(LlmCall.playground_run_id == playground_run_id)
            .order_by(LlmCall.started_at.desc(), LlmCall.id.desc())
            .limit(1)
        )
        return rows.first()

    # --- Aggregates ----------------------------------------------------------------
    #
    # Each method is one query. Coarser totals are added up from these by the caller, so
    # a usage summary costs a handful of round trips whatever it shows.

    async def usage_by_day_and_model(
        self, selection: LlmCallFilter, *, timezone_name: str
    ) -> list[DailyModelUsage]:
        """Totals per local calendar day and requested model, oldest day first."""
        day = func.date(func.timezone(timezone_name, LlmCall.started_at)).label("day")
        rows = await self._session.execute(
            select(day, LlmCall.requested_model.label("model"), *_usage_columns())
            .where(*selection.conditions())
            .group_by(day, LlmCall.requested_model)
            .order_by(day, LlmCall.requested_model)
        )
        return [DailyModelUsage(day=row.day, model=row.model, totals=_totals(row)) for row in rows]

    async def usage_by_origin_and_operation(
        self, selection: LlmCallFilter
    ) -> list[OriginOperationUsage]:
        rows = await self._session.execute(
            select(LlmCall.origin, LlmCall.operation, *_usage_columns())
            .where(*selection.conditions())
            .group_by(LlmCall.origin, LlmCall.operation)
            .order_by(LlmCall.origin, LlmCall.operation)
        )
        return [
            OriginOperationUsage(
                origin=LlmCallOrigin(row.origin),
                operation=LlmOperation(row.operation),
                totals=_totals(row),
            )
            for row in rows
        ]

    async def latency(self, selection: LlmCallFilter) -> LatencyPercentiles:
        """Median and 95th percentile duration of the calls that succeeded."""
        succeeded = [*selection.conditions(), LlmCall.status == LlmCallStatus.SUCCEEDED.value]
        row = (
            await self._session.execute(
                select(
                    func.percentile_cont(0.5).within_group(LlmCall.duration_ms).label("p50"),
                    func.percentile_cont(0.95).within_group(LlmCall.duration_ms).label("p95"),
                ).where(*succeeded)
            )
        ).one()
        return LatencyPercentiles(
            p50_ms=float(row.p50) if row.p50 is not None else None,
            p95_ms=float(row.p95) if row.p95 is not None else None,
        )

    async def errors(self, selection: LlmCallFilter) -> list[ErrorCount]:
        """Failed calls grouped by error code, most frequent first."""
        failed = [*selection.conditions(), LlmCall.error_code.is_not(None)]
        rows = await self._session.execute(
            select(
                LlmCall.error_code,
                func.count().label("calls"),
                func.max(LlmCall.started_at).label("last_seen_at"),
            )
            .where(*failed)
            .group_by(LlmCall.error_code)
            .order_by(func.count().desc(), LlmCall.error_code)
        )
        return [
            ErrorCount(
                error_code=str(row.error_code), calls=int(row.calls), last_seen_at=row.last_seen_at
            )
            for row in rows
        ]
