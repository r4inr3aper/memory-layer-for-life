"""Evaluation runs: starting them, storing their results, and importing old reports.

An evaluation sends golden cases to a model and scores the answers. That work lives in
the ``evaluation`` package. This service adds what the application needs around it:

* A stored record of every run and every case, written while the run is going, so a run
  can be watched and compared with earlier ones.
* One run at a time per process, started in the background or awaited inline.
* A clean end for a run that is cancelled or whose process stops.
* Import of report files written before results were stored.

An evaluation calls a model twice per case, so it costs money and sends the dataset's
messages to the provider. Nothing here starts one on its own.
"""

import asyncio
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import Any, Final

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.core.config import EffortLevel
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import (
    EvaluationCaseOutcome,
    EvaluationRunStatus,
    EvaluationTrigger,
    LlmCallOrigin,
)
from app.domain.errors import (
    EvaluationDatasetUnavailableError,
    EvaluationInProgressError,
    EvaluationNotRunningError,
    InvalidEvaluationSelectionError,
    ProviderNotConfiguredError,
    UnsupportedModelError,
)
from app.integrations.extraction.base import Extractor
from app.integrations.extraction.factory import ExtractorFactory
from app.integrations.llm_calls import LlmCallContext
from app.models.evaluation import EvaluationCaseResult, EvaluationRun
from app.repositories.evaluation_repository import EvaluationRepository
from app.services.playground import allowed_models
from evaluation.golden import GoldenCase, GoldenDatasetError, load_golden_cases
from evaluation.judge import JUDGE_PROMPT_VERSION, Judge, JudgeFactory
from evaluation.report import build_report, case_document
from evaluation.runner import CaseResult, run_evaluation
from evaluation.runner import EvaluationRun as EvaluationOutcome
from evaluation.stored import StoredCase, priced_usage, read_report, stored_case

logger = structlog.get_logger(__name__)

_PREVIEW_CHARS: Final = 80
# Stale runs are looked for at most this often when the check is not forced.
_REAP_INTERVAL_SECONDS: Final = 60.0

_CANCELLED_MESSAGE: Final = "The run was cancelled."
_INTERRUPTED_MESSAGE: Final = "The process running this evaluation stopped before it finished."


@dataclass(frozen=True, slots=True)
class EvaluationOptions:
    """What to evaluate and with which models. ``None`` means the configured default."""

    extractor_model: str | None = None
    extraction_effort: EffortLevel | None = None
    judge_model: str | None = None
    judge_effort: EffortLevel = "high"
    case_ids: tuple[str, ...] | None = None
    concurrency: int = 6


@dataclass(frozen=True, slots=True)
class DatasetCase:
    case_id: str
    expected_outcome: str
    tags: tuple[str, ...]
    message_count: int
    preview: str


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    """The golden dataset as found on this machine. ``problem`` says why it is missing."""

    available: bool
    name: str
    cases: tuple[DatasetCase, ...] = ()
    problem: str | None = None


@dataclass(frozen=True, slots=True)
class CompletedEvaluation:
    run_id: uuid.UUID
    outcome: EvaluationOutcome


@dataclass(frozen=True, slots=True)
class _Prepared:
    run_id: uuid.UUID
    cases: tuple[GoldenCase, ...]
    extractor: Extractor
    judge: Judge
    concurrency: int


@dataclass(slots=True)
class _Job:
    run_id: uuid.UUID
    task: asyncio.Task[None]
    # What the run becomes if its task is cancelled. Cancelling on request changes it.
    stop_status: EvaluationRunStatus = EvaluationRunStatus.INTERRUPTED


def _case_row(run_id: uuid.UUID, position: int, case: StoredCase) -> EvaluationCaseResult:
    return EvaluationCaseResult(
        id=new_uuid(),
        evaluation_run_id=run_id,
        case_id=case.case_id,
        position=position,
        outcome=case.outcome.value,
        expected_outcome=case.expected_outcome.value,
        produced_disposition=(
            case.produced_disposition.value if case.produced_disposition is not None else None
        ),
        failed_checks=list(case.failed_checks),
        error=case.error,
        document=case.document,
    )


class EvaluationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        extractors: ExtractorFactory,
        judges: JudgeFactory,
        *,
        dataset_path: Path,
        default_model: str,
        default_effort: EffortLevel,
        stale_after: timedelta,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._extractors = extractors
        self._judges = judges
        self._dataset_path = dataset_path
        self._default_model = default_model
        self._default_effort: EffortLevel = default_effort
        self._stale_after = stale_after
        self._clock = clock
        self._job: _Job | None = None
        self._start_lock = asyncio.Lock()
        self._next_reap_at = 0.0

    # --- Dataset -------------------------------------------------------------------

    def load_dataset(self) -> list[GoldenCase]:
        """Read the golden dataset. Raises ``EvaluationDatasetUnavailableError``."""
        try:
            return load_golden_cases(self._dataset_path)
        except FileNotFoundError as error:
            raise EvaluationDatasetUnavailableError(
                f"The dataset file '{self._dataset_path.name}' is not on this machine."
            ) from error
        except GoldenDatasetError as error:
            # The loader's own message can quote the dataset, so it is not passed on.
            raise EvaluationDatasetUnavailableError(
                f"The dataset file '{self._dataset_path.name}' is malformed."
            ) from error

    @property
    def dataset_available(self) -> bool:
        return self._dataset_path.is_file()

    def dataset_info(self) -> DatasetInfo:
        """Describe the dataset without failing when it is missing."""
        name = self._dataset_path.name
        try:
            cases = self.load_dataset()
        except EvaluationDatasetUnavailableError as error:
            return DatasetInfo(available=False, name=name, problem=error.message)
        return DatasetInfo(
            available=True,
            name=name,
            cases=tuple(
                DatasetCase(
                    case_id=case.case_id,
                    expected_outcome=case.expected.outcome.value,
                    tags=case.tags,
                    message_count=len(case.input.messages),
                    preview=case.input.messages[0].content[:_PREVIEW_CHARS],
                )
                for case in cases
            ),
        )

    # --- Running -------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._job is not None and not self._job.task.done()

    async def start(
        self,
        options: EvaluationOptions,
        *,
        trigger: EvaluationTrigger = EvaluationTrigger.CONSOLE,
    ) -> uuid.UUID:
        """Start a run in the background and return its id.

        Raises ``EvaluationInProgressError`` when one is already running here.
        """
        async with self._start_lock:
            if self.is_running:
                raise EvaluationInProgressError
            await self.reap_stale(force=True)
            prepared = await self._prepare(options, trigger)
            task = asyncio.create_task(
                self._run_in_background(prepared), name=f"evaluation-{prepared.run_id}"
            )
            self._job = _Job(prepared.run_id, task)
            return prepared.run_id

    async def run(
        self,
        options: EvaluationOptions,
        *,
        trigger: EvaluationTrigger = EvaluationTrigger.CLI,
    ) -> CompletedEvaluation:
        """Run an evaluation and wait for it. The outcome is stored like any other run."""
        prepared = await self._prepare(options, trigger)
        try:
            outcome = await self._execute(prepared)
        except asyncio.CancelledError:
            await asyncio.shield(self._stop(prepared.run_id, EvaluationRunStatus.INTERRUPTED))
            raise
        except Exception as error:
            await self._fail(prepared.run_id, error)
            raise
        return CompletedEvaluation(prepared.run_id, outcome)

    async def cancel(self, run_id: uuid.UUID) -> None:
        """Stop the run this process is executing.

        Raises ``EvaluationNotRunningError`` when this process is not running it.
        """
        job = self._job
        if job is None or job.run_id != run_id or job.task.done():
            raise EvaluationNotRunningError
        job.stop_status = EvaluationRunStatus.CANCELLED
        job.task.cancel()
        await asyncio.gather(job.task, return_exceptions=True)

    async def shutdown(self) -> None:
        """Stop a running evaluation and mark it interrupted. Called when the process ends."""
        job = self._job
        if job is None or job.task.done():
            return
        job.task.cancel()
        await asyncio.gather(job.task, return_exceptions=True)

    async def wait(self) -> None:
        """Wait for the background run, if any, to end. It never raises the run's error."""
        job = self._job
        if job is not None:
            await asyncio.gather(job.task, return_exceptions=True)

    async def reap_stale(self, *, force: bool = False) -> int:
        """Mark runs whose process disappeared as interrupted. Returns how many.

        A run counts as abandoned when it is still ``running`` but no case has finished
        for longer than the stale period. Unless forced, the check runs at most once a
        minute, so that reading runs stays cheap.
        """
        if not force and time.monotonic() < self._next_reap_at:
            return 0
        self._next_reap_at = time.monotonic() + _REAP_INTERVAL_SECONDS

        now = self._clock()
        own_run_id = self._job.run_id if self.is_running and self._job is not None else None
        async with transaction(self._session_factory) as session:
            stale = await EvaluationRepository(session).lock_running_without_heartbeat_since(
                now - self._stale_after
            )
            reaped = 0
            for run in stale:
                if run.id == own_run_id:
                    continue
                run.status = EvaluationRunStatus.INTERRUPTED.value
                run.finished_at = now
                run.error_message = _INTERRUPTED_MESSAGE
                reaped += 1
            return reaped

    # --- Import --------------------------------------------------------------------

    async def import_report(
        self, report: Mapping[str, Any], *, source_report: str
    ) -> tuple[uuid.UUID, bool]:
        """Store a ``report.json`` document as a finished run.

        ``source_report`` identifies the file. Importing the same one again changes
        nothing. Returns the run id and whether it was created by this call. Raises
        ``evaluation.stored.ReportFormatError`` when the document cannot be read.
        """
        stored = read_report(report)
        async with transaction(self._session_factory) as session:
            repository = EvaluationRepository(session)
            existing = await repository.get_run_by_source_report(source_report)
            if existing is not None:
                return existing.id, False

            run_id = new_uuid()
            totals = stored.totals
            await repository.add_run(
                EvaluationRun(
                    id=run_id,
                    status=EvaluationRunStatus.COMPLETED.value,
                    trigger=EvaluationTrigger.IMPORT.value,
                    dataset_name=self._dataset_path.name,
                    extractor_model=stored.extractor_model,
                    extractor_version=stored.extractor_version,
                    judge_model=stored.judge_model,
                    cases_total=totals.total,
                    cases_passed=totals.passed,
                    cases_failed=totals.failed,
                    cases_not_evaluated=totals.not_evaluated,
                    check_totals=totals.check_totals,
                    not_gating=stored.not_gating,
                    usage=stored.usage,
                    estimated_cost_usd=stored.estimated_cost_usd,
                    # These calls were made before the call log existed.
                    calls_logged=False,
                    source_report=source_report,
                    started_at=stored.generated_at,
                    heartbeat_at=stored.generated_at,
                    finished_at=stored.generated_at,
                    created_at=self._clock(),
                )
            )
            await repository.add_case_results(
                [_case_row(run_id, position, case) for position, case in enumerate(stored.cases)]
            )
            return run_id, True

    async def attach_report_file(self, run_id: uuid.UUID, source_report: str) -> None:
        """Note which report file holds a run, so importing that file later changes nothing."""
        async with transaction(self._session_factory) as session:
            run = await EvaluationRepository(session).get_run_for_update(run_id)
            if run is not None:
                run.source_report = source_report

    # --- Internals -----------------------------------------------------------------

    def _select_cases(self, case_ids: Sequence[str] | None) -> tuple[GoldenCase, ...]:
        cases = self.load_dataset()
        if case_ids is None:
            return tuple(cases)
        wanted = set(case_ids)
        unknown = sorted(wanted - {case.case_id for case in cases})
        if unknown:
            raise InvalidEvaluationSelectionError(
                f"The dataset has no case named: {', '.join(unknown)}."
            )
        return tuple(case for case in cases if case.case_id in wanted)

    async def _prepare(self, options: EvaluationOptions, trigger: EvaluationTrigger) -> _Prepared:
        """Check that the run can happen, then record that it started."""
        extractor_model = options.extractor_model or self._default_model
        judge_model = options.judge_model or extractor_model
        offered = allowed_models(self._default_model)
        for model in (extractor_model, judge_model):
            if model not in offered:
                raise UnsupportedModelError(model)
        extraction_effort: EffortLevel = options.extraction_effort or self._default_effort

        run_id = new_uuid()
        extractor = self._extractors.build(model=extractor_model, effort=extraction_effort)
        judge = self._judges.build(
            model=judge_model,
            effort=options.judge_effort,
            context=LlmCallContext(origin=LlmCallOrigin.EVALUATION, evaluation_run_id=run_id),
        )
        if extractor is None or judge is None:
            raise ProviderNotConfiguredError
        cases = self._select_cases(options.case_ids)

        now = self._clock()
        async with transaction(self._session_factory) as session:
            await EvaluationRepository(session).add_run(
                EvaluationRun(
                    id=run_id,
                    status=EvaluationRunStatus.RUNNING.value,
                    trigger=trigger.value,
                    dataset_name=self._dataset_path.name,
                    extractor_model=extractor.descriptor.model,
                    extractor_version=extractor.descriptor.version,
                    extraction_effort=extraction_effort,
                    judge_model=judge.model,
                    judge_effort=options.judge_effort,
                    judge_prompt_version=JUDGE_PROMPT_VERSION,
                    concurrency=options.concurrency,
                    cases_total=len(cases),
                    started_at=now,
                    heartbeat_at=now,
                    created_at=now,
                )
            )
        logger.info(
            "evaluation_started",
            run_id=str(run_id),
            trigger=trigger.value,
            cases=len(cases),
            extractor_model=extractor.descriptor.model,
            judge_model=judge.model,
        )
        return _Prepared(run_id, cases, extractor, judge, options.concurrency)

    async def _execute(self, prepared: _Prepared) -> EvaluationOutcome:
        outcome = await run_evaluation(
            prepared.cases,
            prepared.extractor,
            prepared.judge,
            concurrency=prepared.concurrency,
            call_context=LlmCallContext(
                origin=LlmCallOrigin.EVALUATION, evaluation_run_id=prepared.run_id
            ),
            on_result=partial(self._store_case, prepared.run_id),
        )
        await self._complete(prepared.run_id, outcome)
        return outcome

    async def _run_in_background(self, prepared: _Prepared) -> None:
        try:
            await self._execute(prepared)
        except asyncio.CancelledError:
            job = self._job
            status = job.stop_status if job is not None else EvaluationRunStatus.INTERRUPTED
            await asyncio.shield(self._stop(prepared.run_id, status))
            raise
        except Exception as error:
            await self._fail(prepared.run_id, error)

    async def _store_case(self, run_id: uuid.UUID, position: int, result: CaseResult) -> None:
        """Store one scored case and move the run's counters and heartbeat."""
        case = stored_case(case_document(result))
        counter = {
            EvaluationCaseOutcome.PASSED: EvaluationRun.cases_passed,
            EvaluationCaseOutcome.FAILED: EvaluationRun.cases_failed,
            EvaluationCaseOutcome.NOT_EVALUATED: EvaluationRun.cases_not_evaluated,
        }[case.outcome]
        async with transaction(self._session_factory) as session:
            await EvaluationRepository(session).add_case_result(_case_row(run_id, position, case))
            # One atomic statement: cases finish concurrently.
            await session.execute(
                update(EvaluationRun)
                .where(EvaluationRun.id == run_id)
                .values({counter.key: counter + 1, EvaluationRun.heartbeat_at.key: self._clock()})
            )

    async def _complete(self, run_id: uuid.UUID, outcome: EvaluationOutcome) -> None:
        now = self._clock()
        report = build_report(outcome, generated_at=now)
        usage, cost = priced_usage(report["usage"])
        async with transaction(self._session_factory) as session:
            run = await EvaluationRepository(session).get_run_for_update(run_id)
            if run is None:  # pragma: no cover - the row was written when the run started
                return
            run.status = EvaluationRunStatus.COMPLETED.value
            run.cases_passed = len(outcome.passed)
            run.cases_failed = len(outcome.failed)
            run.cases_not_evaluated = len(outcome.not_evaluated)
            run.check_totals = report["checks"]
            run.not_gating = report["reported_not_gating"]
            run.usage = usage
            run.estimated_cost_usd = cost
            run.heartbeat_at = now
            run.finished_at = now
        logger.info(
            "evaluation_completed",
            run_id=str(run_id),
            passed=len(outcome.passed),
            failed=len(outcome.failed),
            not_evaluated=len(outcome.not_evaluated),
        )

    async def _stop(self, run_id: uuid.UUID, status: EvaluationRunStatus) -> None:
        message = (
            _CANCELLED_MESSAGE if status is EvaluationRunStatus.CANCELLED else _INTERRUPTED_MESSAGE
        )
        await self._end(run_id, status, message)
        logger.warning("evaluation_stopped", run_id=str(run_id), status=status.value)

    async def _fail(self, run_id: uuid.UUID, error: Exception) -> None:
        # The engine hides bound parameters, so this traceback carries no message text.
        logger.exception("evaluation_failed", run_id=str(run_id), error_type=type(error).__name__)
        await self._end(run_id, EvaluationRunStatus.FAILED, f"Unexpected {type(error).__name__}.")

    async def _end(self, run_id: uuid.UUID, status: EvaluationRunStatus, message: str) -> None:
        """Close a run that did not complete. A run that already ended is left alone."""
        now = self._clock()
        async with transaction(self._session_factory) as session:
            run = await EvaluationRepository(session).get_run_for_update(run_id)
            if run is None or run.status != EvaluationRunStatus.RUNNING.value:
                return
            run.status = status.value
            run.error_message = message
            run.finished_at = now
