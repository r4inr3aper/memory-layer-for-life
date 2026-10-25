"""Evaluation runs: storing results while they run, stopping them, and importing reports."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import EvaluationRunStatus, EvaluationTrigger
from app.domain.errors import (
    EvaluationDatasetUnavailableError,
    EvaluationInProgressError,
    EvaluationNotRunningError,
    ExtractionBillingError,
    InvalidEvaluationSelectionError,
    ProviderNotConfiguredError,
    UnsupportedModelError,
)
from app.integrations.anthropic_calls import AnthropicCallObserver
from app.integrations.extraction.base import (
    ExtractionRequest,
    ExtractionResponse,
    Extractor,
)
from app.integrations.extraction.factory import FixedExtractorFactory
from app.models.evaluation import EvaluationCaseResult, EvaluationRun
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.llm_call_repository import LlmCallFilter, LlmCallRepository
from app.services.evaluations import EvaluationOptions, EvaluationService
from app.services.llm_call_log import LlmCallLog
from evaluation.judge import JUDGE_PROMPT_VERSION, FixedJudgeFactory, Judge
from evaluation.report import build_report
from evaluation.runner import CaseResult
from evaluation.runner import EvaluationRun as EvaluationOutcome
from evaluation.scoring import score_case
from evaluation.stored import ReportFormatError
from tests.support.call_log import LoggedScriptedExtractor
from tests.support.datasets import three_cases, write_dataset
from tests.support.extraction import DEFAULT_DESCRIPTOR, ScriptedExtractor
from tests.support.pipeline import FakeClock
from tests.unit.test_evaluation import ScriptedJudge, expense, make_case, verdict

SessionFactory = async_sessionmaker[AsyncSession]

ONE_AT_A_TIME = EvaluationOptions(concurrency=1)


class BlockingExtractor:
    """Holds every call until released, so a run can be caught while it is going."""

    descriptor = DEFAULT_DESCRIPTOR

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def extract(self, request: ExtractionRequest) -> ExtractionResponse:
        self.started.set()
        await self.release.wait()
        return ExtractionResponse(output=expense(), model="test-model")


def build_service(
    session_factory: SessionFactory,
    dataset: Path,
    extractor: Extractor | None,
    judge: Judge | None,
    clock: FakeClock,
) -> EvaluationService:
    return EvaluationService(
        session_factory,
        FixedExtractorFactory(extractor),
        FixedJudgeFactory(judge),
        dataset_path=dataset,
        default_model="claude-sonnet-5-5",
        default_effort="medium",
        stale_after=timedelta(minutes=15),
        clock=clock,
    )


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    return write_dataset(tmp_path / "golden.jsonl", three_cases())


async def stored_run(session_factory: SessionFactory, run_id: object) -> EvaluationRun:
    async with session_factory() as session:
        run = await EvaluationRepository(session).get_run(run_id)  # type: ignore[arg-type]
        assert run is not None
        return run


async def stored_cases(
    session_factory: SessionFactory, run_id: object
) -> list[EvaluationCaseResult]:
    async with session_factory() as session:
        cases, _ = await EvaluationRepository(session).list_case_results(
            run_id,  # type: ignore[arg-type]
            limit=100,
            offset=0,
        )
        return cases


# --- Running --------------------------------------------------------------------------


async def test_a_run_stores_every_case_and_its_totals(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    extractor = ScriptedExtractor(expense(), expense(), ExtractionBillingError("no credit"))
    service = build_service(session_factory, dataset, extractor, ScriptedJudge(verdict()), clock)

    completed = await service.run(ONE_AT_A_TIME)

    assert completed.outcome.complete is False
    run = await stored_run(session_factory, completed.run_id)
    assert (run.status, run.trigger) == ("completed", "cli")
    assert (run.cases_total, run.cases_passed, run.cases_failed, run.cases_not_evaluated) == (
        3,
        1,
        1,
        1,
    )
    assert (run.extractor_model, run.extractor_version) == ("test-model", "scripted:1")
    assert (run.judge_model, run.judge_effort, run.judge_prompt_version) == (
        "scripted-judge",
        "high",
        JUDGE_PROMPT_VERSION,
    )
    assert (run.extraction_effort, run.concurrency) == ("medium", 1)
    assert run.check_totals["valid_output"] == {"evaluated": 2, "passed": 2}
    assert run.check_totals["abstention"] == {"evaluated": 2, "passed": 1}
    assert run.usage["extraction"]["input_tokens"] == 200
    assert run.usage["judge"]["input_tokens"] == 900
    # Scripted models have no price, so no cost is claimed.
    assert run.estimated_cost_usd is None
    assert run.calls_logged is True
    assert run.source_report is None
    assert run.started_at == run.finished_at == run.heartbeat_at == clock()

    cases = await stored_cases(session_factory, completed.run_id)
    assert [(c.case_id, c.position, c.outcome) for c in cases] == [
        ("pass_1", 0, "passed"),
        ("abstain_1", 1, "failed"),
        ("unreached_1", 2, "not_evaluated"),
    ]
    assert cases[0].document["messages"] == ["500 petrol"]
    assert cases[0].produced_disposition == "extract"
    assert cases[1].failed_checks == ["abstention"]
    assert cases[1].expected_outcome == "abstain"
    assert cases[2].error == "EXTRACTION_PROVIDER_BILLING: no credit"
    assert cases[2].produced_disposition is None


async def test_the_calls_of_a_run_are_logged_against_it(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    observer = AnthropicCallObserver(LlmCallLog(session_factory), clock=clock)
    extractor = LoggedScriptedExtractor(observer, expense())
    service = build_service(session_factory, dataset, extractor, ScriptedJudge(verdict()), clock)

    completed = await service.run(EvaluationOptions(case_ids=("pass_1", "abstain_1")))

    async with session_factory() as session:
        calls, _ = await LlmCallRepository(session).list_calls(
            LlmCallFilter(evaluation_run_id=completed.run_id), limit=10, offset=0
        )
    assert sorted(call.evaluation_case_id or "" for call in calls) == ["abstain_1", "pass_1"]
    assert {call.origin for call in calls} == {"evaluation"}


async def test_a_background_run_completes_and_can_be_waited_for(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    service = build_service(
        session_factory, dataset, ScriptedExtractor(expense()), ScriptedJudge(verdict()), clock
    )

    run_id = await service.start(EvaluationOptions(case_ids=("pass_1",), concurrency=1))
    await service.wait()

    assert service.is_running is False
    run = await stored_run(session_factory, run_id)
    assert (run.status, run.trigger, run.cases_total, run.cases_passed) == (
        "completed",
        "console",
        1,
        1,
    )


async def test_one_evaluation_runs_at_a_time_and_can_be_cancelled(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    extractor = BlockingExtractor()
    service = build_service(session_factory, dataset, extractor, ScriptedJudge(verdict()), clock)

    run_id = await service.start(ONE_AT_A_TIME)
    await extractor.started.wait()
    assert service.is_running is True
    with pytest.raises(EvaluationInProgressError):
        await service.start(ONE_AT_A_TIME)

    await service.cancel(run_id)

    assert service.is_running is False
    run = await stored_run(session_factory, run_id)
    assert run.status == "cancelled"
    assert run.error_message == "The run was cancelled."
    assert run.finished_at == clock()
    assert (run.cases_passed, run.cases_failed, run.cases_not_evaluated) == (0, 0, 0)
    with pytest.raises(EvaluationNotRunningError):
        await service.cancel(run_id)
    with pytest.raises(EvaluationNotRunningError):
        await service.cancel(new_uuid())


async def test_shutdown_marks_a_running_evaluation_interrupted(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    extractor = BlockingExtractor()
    service = build_service(session_factory, dataset, extractor, ScriptedJudge(verdict()), clock)
    run_id = await service.start(ONE_AT_A_TIME)
    await extractor.started.wait()

    await service.shutdown()

    run = await stored_run(session_factory, run_id)
    assert run.status == "interrupted"
    assert "stopped" in (run.error_message or "")
    # Shutting down again, or waiting, is harmless.
    await service.shutdown()
    await service.wait()


async def test_an_unexpected_failure_marks_the_run_failed(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    service = build_service(
        session_factory,
        dataset,
        ScriptedExtractor(RuntimeError("boom")),
        ScriptedJudge(verdict()),
        clock,
    )

    with pytest.raises(RuntimeError):
        await service.run(ONE_AT_A_TIME)

    async with session_factory() as session:
        runs, _ = await EvaluationRepository(session).list_runs(limit=10, offset=0)
    assert [run.status for run in runs] == ["failed"]
    assert runs[0].error_message == "Unexpected RuntimeError."


async def test_a_run_whose_process_vanished_is_marked_interrupted(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    service = build_service(
        session_factory, dataset, ScriptedExtractor(expense()), ScriptedJudge(verdict()), clock
    )
    an_hour_ago = clock() - timedelta(hours=1)
    silent_id, fresh_id = new_uuid(), new_uuid()
    async with transaction(session_factory) as session:
        repository = EvaluationRepository(session)
        for run_id, heartbeat in ((silent_id, an_hour_ago), (fresh_id, clock())):
            await repository.add_run(
                EvaluationRun(
                    id=run_id,
                    status=EvaluationRunStatus.RUNNING.value,
                    trigger=EvaluationTrigger.CONSOLE.value,
                    dataset_name="golden.jsonl",
                    extractor_version="scripted:1",
                    cases_total=3,
                    started_at=an_hour_ago,
                    heartbeat_at=heartbeat,
                    created_at=an_hour_ago,
                )
            )

    assert await service.reap_stale(force=True) == 1

    silent = await stored_run(session_factory, silent_id)
    assert silent.status == "interrupted"
    assert silent.finished_at == clock()
    assert "stopped" in (silent.error_message or "")
    assert (await stored_run(session_factory, fresh_id)).status == "running"
    # The check is rate limited when it is not forced.
    assert await service.reap_stale() == 0


# --- Preconditions --------------------------------------------------------------------


async def test_a_missing_or_malformed_dataset_is_reported_and_blocks_a_run(
    session_factory: SessionFactory, tmp_path: Path, clock: FakeClock
) -> None:
    missing = build_service(
        session_factory,
        tmp_path / "missing.jsonl",
        ScriptedExtractor(expense()),
        ScriptedJudge(verdict()),
        clock,
    )

    info = missing.dataset_info()
    assert info.available is False
    assert "missing.jsonl" in (info.problem or "")
    assert missing.dataset_available is False
    with pytest.raises(EvaluationDatasetUnavailableError):
        await missing.start(ONE_AT_A_TIME)

    broken = tmp_path / "broken.jsonl"
    broken.write_text("{not json\n", encoding="utf-8")
    malformed = build_service(
        session_factory, broken, ScriptedExtractor(expense()), ScriptedJudge(verdict()), clock
    )
    assert "malformed" in (malformed.dataset_info().problem or "")


async def test_the_dataset_is_described_without_its_full_text(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    service = build_service(
        session_factory, dataset, ScriptedExtractor(expense()), ScriptedJudge(verdict()), clock
    )

    info = service.dataset_info()

    assert info.available is True
    assert info.name == "golden.jsonl"
    assert [case.case_id for case in info.cases] == ["pass_1", "abstain_1", "unreached_1"]
    assert info.cases[1].expected_outcome == "abstain"
    assert info.cases[1].preview == "14 15"
    assert info.cases[1].message_count == 1
    assert info.cases[0].tags == ("test",)


async def test_unknown_cases_and_models_are_refused_before_anything_starts(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    extractor = ScriptedExtractor(expense())
    service = build_service(session_factory, dataset, extractor, ScriptedJudge(verdict()), clock)

    with pytest.raises(InvalidEvaluationSelectionError, match="nope_1"):
        await service.start(EvaluationOptions(case_ids=("pass_1", "nope_1")))
    with pytest.raises(UnsupportedModelError):
        await service.start(EvaluationOptions(extractor_model="gpt-9"))
    with pytest.raises(UnsupportedModelError):
        await service.start(EvaluationOptions(judge_model="gpt-9"))

    assert extractor.call_count == 0
    async with session_factory() as session:
        _, total = await EvaluationRepository(session).list_runs(limit=10, offset=0)
    assert total == 0


async def test_an_evaluation_needs_a_configured_provider(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    no_judge = build_service(session_factory, dataset, ScriptedExtractor(expense()), None, clock)
    no_extractor = build_service(session_factory, dataset, None, ScriptedJudge(verdict()), clock)

    with pytest.raises(ProviderNotConfiguredError):
        await no_judge.start(ONE_AT_A_TIME)
    with pytest.raises(ProviderNotConfiguredError):
        await no_extractor.run(ONE_AT_A_TIME)


# --- Import ---------------------------------------------------------------------------


def sample_report() -> dict[str, object]:
    passing = make_case(case_id="pass_1", attributes={"amount": 500, "currency": None})
    abstaining = make_case(case_id="abstain_1", outcome="abstain", texts=("14 15",))
    results = (
        CaseResult(
            passing,
            score_case(passing, expense(), [verdict()]),
            output=expense(),
            verdicts=(verdict(),),
        ),
        CaseResult(abstaining, score_case(abstaining, expense()), output=expense()),
    )
    outcome = EvaluationOutcome(
        results=results,
        extractor_model="claude-sonnet-5-5",
        extractor_version="anthropic:1",
        judge_model="claude-sonnet-5-5",
    )
    return build_report(outcome, generated_at=datetime(2026, 10, 11, 19, 29, 20, tzinfo=UTC))


async def test_a_report_file_is_imported_once(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    service = build_service(session_factory, dataset, None, None, clock)
    report = sample_report()

    run_id, created = await service.import_report(report, source_report="20261011T192920Z")
    again, created_again = await service.import_report(report, source_report="20261011T192920Z")

    assert created is True
    assert (again, created_again) == (run_id, False)
    run = await stored_run(session_factory, run_id)
    assert (run.status, run.trigger, run.calls_logged) == ("completed", "import", False)
    assert run.source_report == "20261011T192920Z"
    assert run.started_at == run.finished_at == datetime(2026, 10, 11, 19, 29, 20, tzinfo=UTC)
    assert (run.cases_total, run.cases_passed, run.cases_failed, run.cases_not_evaluated) == (
        2,
        1,
        1,
        0,
    )
    assert run.extractor_model == "claude-sonnet-5-5"
    assert run.estimated_cost_usd == Decimal(0)
    assert run.usage["extraction"]["model"] == "claude-sonnet-5-5"
    cases = await stored_cases(session_factory, run_id)
    assert [(c.case_id, c.outcome) for c in cases] == [
        ("pass_1", "passed"),
        ("abstain_1", "failed"),
    ]


async def test_a_malformed_report_is_refused(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    service = build_service(session_factory, dataset, None, None, clock)

    with pytest.raises(ReportFormatError):
        await service.import_report({"summary": {}}, source_report="broken")


async def test_a_stored_run_remembers_its_report_file(
    session_factory: SessionFactory, dataset: Path, clock: FakeClock
) -> None:
    service = build_service(
        session_factory, dataset, ScriptedExtractor(expense()), ScriptedJudge(verdict()), clock
    )
    completed = await service.run(EvaluationOptions(case_ids=("pass_1",)))

    await service.attach_report_file(completed.run_id, "20261012T100000Z")

    assert (await stored_run(session_factory, completed.run_id)).source_report == "20261012T100000Z"
    # Importing that file later changes nothing.
    assert await service.import_report(sample_report(), source_report="20261012T100000Z") == (
        completed.run_id,
        False,
    )
