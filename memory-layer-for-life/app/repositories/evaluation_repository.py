import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, case, func, select

from app.domain.enums import EvaluationCaseOutcome, EvaluationRunStatus
from app.models.evaluation import EvaluationCaseResult, EvaluationRun
from app.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class CaseFailureCount:
    """How often one case failed across the runs that evaluated it."""

    case_id: str
    failed: int
    evaluated: int


@dataclass(frozen=True, slots=True)
class UnloggedSpend:
    """Cost of evaluation runs whose model calls are not in the call log."""

    runs: int
    estimated_cost_usd: Decimal


class EvaluationRepository(BaseRepository):
    """Persistence of evaluation runs and their case results."""

    # --- Runs ----------------------------------------------------------------------

    async def add_run(self, run: EvaluationRun) -> EvaluationRun:
        self._session.add(run)
        await self._session.flush()
        return run

    async def get_run(self, run_id: uuid.UUID) -> EvaluationRun | None:
        return await self._session.get(EvaluationRun, run_id)

    async def get_run_for_update(self, run_id: uuid.UUID) -> EvaluationRun | None:
        """Load a run and hold a row lock on it until the transaction ends."""
        rows = await self._session.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return rows.first()

    async def get_run_by_source_report(self, source_report: str) -> EvaluationRun | None:
        rows = await self._session.scalars(
            select(EvaluationRun).where(EvaluationRun.source_report == source_report)
        )
        return rows.first()

    async def list_runs(
        self,
        *,
        status: EvaluationRunStatus | None = None,
        extractor_model: str | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[EvaluationRun], int]:
        """Page through runs, newest first. Returns the page and the total match count."""
        conditions: list[ColumnElement[bool]] = []
        if status is not None:
            conditions.append(EvaluationRun.status == status.value)
        if extractor_model is not None:
            conditions.append(EvaluationRun.extractor_model == extractor_model)
        total = await self._session.scalar(
            select(func.count()).select_from(EvaluationRun).where(*conditions)
        )
        rows = await self._session.scalars(
            select(EvaluationRun)
            .where(*conditions)
            .order_by(EvaluationRun.started_at.desc(), EvaluationRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def lock_running_without_heartbeat_since(self, moment: datetime) -> list[EvaluationRun]:
        """Lock the runs that are still ``running`` but have been silent since ``moment``."""
        rows = await self._session.scalars(
            select(EvaluationRun)
            .where(
                EvaluationRun.status == EvaluationRunStatus.RUNNING.value,
                EvaluationRun.heartbeat_at < moment,
            )
            .order_by(EvaluationRun.started_at)
            .with_for_update(skip_locked=True)
        )
        return list(rows)

    async def unlogged_spend(self) -> UnloggedSpend:
        row = (
            await self._session.execute(
                select(
                    func.count().label("runs"),
                    func.coalesce(func.sum(EvaluationRun.estimated_cost_usd), 0).label("cost"),
                ).where(EvaluationRun.calls_logged.is_(False))
            )
        ).one()
        return UnloggedSpend(runs=int(row.runs), estimated_cost_usd=Decimal(row.cost))

    # --- Case results --------------------------------------------------------------

    async def add_case_result(self, result: EvaluationCaseResult) -> EvaluationCaseResult:
        self._session.add(result)
        await self._session.flush()
        return result

    async def add_case_results(self, results: list[EvaluationCaseResult]) -> None:
        self._session.add_all(results)
        await self._session.flush()

    async def get_case_result(self, run_id: uuid.UUID, case_id: str) -> EvaluationCaseResult | None:
        rows = await self._session.scalars(
            select(EvaluationCaseResult).where(
                EvaluationCaseResult.evaluation_run_id == run_id,
                EvaluationCaseResult.case_id == case_id,
            )
        )
        return rows.first()

    async def list_case_results(
        self,
        run_id: uuid.UUID,
        *,
        outcome: EvaluationCaseOutcome | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[EvaluationCaseResult], int]:
        """Page through a run's cases in dataset order."""
        conditions: list[ColumnElement[bool]] = [EvaluationCaseResult.evaluation_run_id == run_id]
        if outcome is not None:
            conditions.append(EvaluationCaseResult.outcome == outcome.value)
        total = await self._session.scalar(
            select(func.count()).select_from(EvaluationCaseResult).where(*conditions)
        )
        rows = await self._session.scalars(
            select(EvaluationCaseResult)
            .where(*conditions)
            .order_by(EvaluationCaseResult.position, EvaluationCaseResult.case_id)
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def case_failure_counts(
        self, *, extractor_model: str | None = None, limit: int
    ) -> list[CaseFailureCount]:
        """Cases that failed at least once in a completed run, most failures first.

        A case that fails in every run points at the case or its label. A case that fails
        now and then points at the model or the judge.
        """
        failed = case(
            (EvaluationCaseResult.outcome == EvaluationCaseOutcome.FAILED.value, 1), else_=0
        )
        conditions: list[ColumnElement[bool]] = [
            EvaluationRun.status == EvaluationRunStatus.COMPLETED.value,
            EvaluationCaseResult.outcome != EvaluationCaseOutcome.NOT_EVALUATED.value,
        ]
        if extractor_model is not None:
            conditions.append(EvaluationRun.extractor_model == extractor_model)
        rows = await self._session.execute(
            select(
                EvaluationCaseResult.case_id,
                func.sum(failed).label("failed"),
                func.count().label("evaluated"),
            )
            .join(EvaluationRun, EvaluationRun.id == EvaluationCaseResult.evaluation_run_id)
            .where(*conditions)
            .group_by(EvaluationCaseResult.case_id)
            .having(func.sum(failed) > 0)
            .order_by(func.sum(failed).desc(), EvaluationCaseResult.case_id)
            .limit(limit)
        )
        return [
            CaseFailureCount(
                case_id=row.case_id, failed=int(row.failed), evaluated=int(row.evaluated)
            )
            for row in rows
        ]
