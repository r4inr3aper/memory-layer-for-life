"""Read side of the test console: the call log, usage, test calls, and evaluations.

Entities are returned as loaded. They are read through the request's session and turned
into response schemas before it closes. Aggregates are plain immutable values.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import (
    EvaluationCaseOutcome,
    EvaluationRunStatus,
    LlmCallOrigin,
    LlmOperation,
)
from app.domain.errors import RecordNotFoundError
from app.models.evaluation import EvaluationCaseResult, EvaluationRun
from app.models.llm_call import LlmCall
from app.models.playground_run import PlaygroundRun
from app.repositories.evaluation_repository import (
    CaseFailureCount,
    EvaluationRepository,
    UnloggedSpend,
)
from app.repositories.llm_call_repository import (
    DailyModelUsage,
    ErrorCount,
    LatencyPercentiles,
    LlmCallFilter,
    LlmCallRepository,
    UsageTotals,
)
from app.repositories.pipeline_stats_repository import PipelineStats, PipelineStatsRepository
from app.repositories.playground_repository import PlaygroundRepository
from app.services.queries import PageResult


@dataclass(frozen=True, slots=True)
class UsageSummary:
    """Usage of the selected calls, cut several ways.

    ``earlier_evaluations`` is the cost of evaluation runs that were imported from report
    files. Their calls were made before the call log existed, so they are in none of the
    other figures.
    """

    totals: UsageTotals
    latency: LatencyPercentiles
    by_model: tuple[tuple[str, UsageTotals], ...]
    by_origin: tuple[tuple[LlmCallOrigin, UsageTotals], ...]
    by_operation: tuple[tuple[LlmOperation, UsageTotals], ...]
    by_day: tuple[DailyModelUsage, ...]
    errors: tuple[ErrorCount, ...]
    earlier_evaluations: UnloggedSpend
    first_day: date | None
    last_day: date | None


def _grouped[KeyT](pairs: list[tuple[KeyT, UsageTotals]]) -> tuple[tuple[KeyT, UsageTotals], ...]:
    """Add up totals per key, largest spend first, then most calls."""
    sums: dict[KeyT, UsageTotals] = defaultdict(UsageTotals)
    for key, totals in pairs:
        sums[key] = sums[key] + totals
    return tuple(
        sorted(
            sums.items(),
            key=lambda item: (-item[1].estimated_cost_usd, -item[1].calls, str(item[0])),
        )
    )


class ConsoleQueryService:
    def __init__(self, session: AsyncSession, *, timezone_name: str) -> None:
        self._calls = LlmCallRepository(session)
        self._playground = PlaygroundRepository(session)
        self._evaluations = EvaluationRepository(session)
        self._stats = PipelineStatsRepository(session)
        self._timezone_name = timezone_name

    @property
    def timezone_name(self) -> str:
        return self._timezone_name

    # --- Model calls ---------------------------------------------------------------

    async def list_calls(
        self, selection: LlmCallFilter, *, limit: int, offset: int
    ) -> PageResult[LlmCall]:
        calls, total = await self._calls.list_calls(selection, limit=limit, offset=offset)
        return PageResult(items=tuple(calls), total=total)

    async def get_call(self, call_id: uuid.UUID) -> LlmCall:
        call = await self._calls.get(call_id)
        if call is None:
            raise RecordNotFoundError("Model call", str(call_id))
        return call

    async def usage_summary(self, selection: LlmCallFilter) -> UsageSummary:
        by_day = await self._calls.usage_by_day_and_model(
            selection, timezone_name=self._timezone_name
        )
        by_source = await self._calls.usage_by_origin_and_operation(selection)
        totals = UsageTotals()
        for entry in by_day:
            totals = totals + entry.totals
        return UsageSummary(
            totals=totals,
            latency=await self._calls.latency(selection),
            by_model=_grouped([(entry.model, entry.totals) for entry in by_day]),
            by_origin=_grouped([(entry.origin, entry.totals) for entry in by_source]),
            by_operation=_grouped([(entry.operation, entry.totals) for entry in by_source]),
            by_day=tuple(by_day),
            errors=tuple(await self._calls.errors(selection)),
            earlier_evaluations=await self._evaluations.unlogged_spend(),
            first_day=by_day[0].day if by_day else None,
            last_day=by_day[-1].day if by_day else None,
        )

    # --- Test calls ----------------------------------------------------------------

    async def list_playground_runs(self, *, limit: int, offset: int) -> PageResult[PlaygroundRun]:
        runs, total = await self._playground.list_runs(limit=limit, offset=offset)
        return PageResult(items=tuple(runs), total=total)

    # --- Evaluations ---------------------------------------------------------------

    async def list_evaluation_runs(
        self,
        *,
        status: EvaluationRunStatus | None,
        extractor_model: str | None,
        limit: int,
        offset: int,
    ) -> PageResult[EvaluationRun]:
        runs, total = await self._evaluations.list_runs(
            status=status, extractor_model=extractor_model, limit=limit, offset=offset
        )
        return PageResult(items=tuple(runs), total=total)

    async def get_evaluation_run(self, run_id: uuid.UUID) -> EvaluationRun:
        run = await self._evaluations.get_run(run_id)
        if run is None:
            raise RecordNotFoundError("Evaluation run", str(run_id))
        return run

    async def list_evaluation_cases(
        self,
        run_id: uuid.UUID,
        *,
        outcome: EvaluationCaseOutcome | None,
        limit: int,
        offset: int,
    ) -> PageResult[EvaluationCaseResult]:
        await self.get_evaluation_run(run_id)
        cases, total = await self._evaluations.list_case_results(
            run_id, outcome=outcome, limit=limit, offset=offset
        )
        return PageResult(items=tuple(cases), total=total)

    async def get_evaluation_case(self, run_id: uuid.UUID, case_id: str) -> EvaluationCaseResult:
        case = await self._evaluations.get_case_result(run_id, case_id)
        if case is None:
            raise RecordNotFoundError("Evaluation case", f"{run_id}/{case_id}")
        return case

    async def failing_cases(
        self, *, extractor_model: str | None, limit: int
    ) -> tuple[CaseFailureCount, ...]:
        return tuple(
            await self._evaluations.case_failure_counts(
                extractor_model=extractor_model, limit=limit
            )
        )

    # --- Pipeline ------------------------------------------------------------------

    async def pipeline_stats(self) -> PipelineStats:
        return await self._stats.stats()


def cost_as_float(cost: Decimal | None) -> float | None:
    """Money leaves the API as a JSON number."""
    return float(cost) if cost is not None else None
