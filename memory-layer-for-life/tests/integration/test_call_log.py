"""The model call log: rows, constraints, aggregates, and the runs that calls link to."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import new_uuid
from app.domain.enums import LlmCallOrigin, LlmCallStatus, LlmOperation, ProcessingStatus
from app.domain.errors import TransientExtractionError
from app.integrations.anthropic_calls import AnthropicCallObserver
from app.models.llm_call import LlmCall
from app.repositories.llm_call_repository import LlmCallFilter, LlmCallRepository, UsageTotals
from app.services.llm_call_log import LlmCallLog
from tests.integration.conftest import HarnessFactory
from tests.support.call_log import T0, LoggedScriptedExtractor, make_record
from tests.support.extraction import extraction
from tests.support.pipeline import FakeClock

SessionFactory = async_sessionmaker[AsyncSession]


async def stored_calls(session_factory: SessionFactory, **filters: Any) -> list[LlmCall]:
    async with session_factory() as session:
        calls, _ = await LlmCallRepository(session).list_calls(
            LlmCallFilter(**filters), limit=100, offset=0
        )
        return calls


# --- Rows -----------------------------------------------------------------------------


async def test_a_call_is_stored_with_its_estimated_cost(session_factory: SessionFactory) -> None:
    await LlmCallLog(session_factory).record(make_record())

    (row,) = await stored_calls(session_factory)
    # Haiku: 10k input at $0.10 per million, 1k output at $0.50 per million.
    assert row.estimated_cost_usd == Decimal("0.001500")
    assert (row.status, row.origin, row.operation) == ("succeeded", "other", "extraction")
    assert row.requested_model == "claude-haiku-5-5"
    assert row.started_at == T0
    assert row.created_at is not None


async def test_the_cost_follows_the_model_that_answered(session_factory: SessionFactory) -> None:
    await LlmCallLog(session_factory).record(
        make_record(model="claude-sonnet-5-5", response_model="claude-opus-4-8")
    )

    (row,) = await stored_calls(session_factory)
    # Opus 4.8: 10k input at $5 per million, 1k output at $25 per million.
    assert row.estimated_cost_usd == Decimal("0.075000")
    assert (row.requested_model, row.response_model) == ("claude-sonnet-5-5", "claude-opus-4-8")


async def test_calls_are_listed_newest_first_and_filtered(session_factory: SessionFactory) -> None:
    log = LlmCallLog(session_factory)
    await log.record(make_record(started_at=T0))
    await log.record(
        make_record(
            started_at=T0 + timedelta(hours=1),
            operation=LlmOperation.JUDGE,
            model="claude-sonnet-5-5",
            status=LlmCallStatus.FAILED,
        )
    )
    await log.record(make_record(started_at=T0 + timedelta(hours=2), model="claude-sonnet-5-5"))

    async def ids(**filters: Any) -> list[tuple[str, str]]:
        return [
            (c.requested_model, c.operation) for c in await stored_calls(session_factory, **filters)
        ]

    assert await ids() == [
        ("claude-sonnet-5-5", "extraction"),
        ("claude-sonnet-5-5", "judge"),
        ("claude-haiku-5-5", "extraction"),
    ]
    assert await ids(status=LlmCallStatus.FAILED) == [("claude-sonnet-5-5", "judge")]
    assert await ids(operation=LlmOperation.JUDGE) == [("claude-sonnet-5-5", "judge")]
    assert await ids(model="claude-haiku-5-5") == [("claude-haiku-5-5", "extraction")]
    assert len(await ids(started_from=T0 + timedelta(hours=1))) == 2
    assert len(await ids(started_before=T0 + timedelta(hours=1))) == 1

    async with session_factory() as session:
        page, total = await LlmCallRepository(session).list_calls(
            LlmCallFilter(), limit=1, offset=1
        )
    assert total == 3
    assert [call.operation for call in page] == ["judge"]


# --- Aggregates -----------------------------------------------------------------------


async def test_usage_is_summed_per_local_day_and_model(session_factory: SessionFactory) -> None:
    log = LlmCallLog(session_factory)
    # T0 is 23:00 UTC on 11 October, which is already 12 October in Kolkata.
    later = T0 + timedelta(hours=5)
    await log.record(make_record(started_at=T0))
    await log.record(make_record(started_at=later))
    await log.record(make_record(started_at=later, model="claude-sonnet-5-5"))

    async with session_factory() as session:
        repository = LlmCallRepository(session)
        kolkata = await repository.usage_by_day_and_model(
            LlmCallFilter(), timezone_name="Asia/Kolkata"
        )
        utc = await repository.usage_by_day_and_model(LlmCallFilter(), timezone_name="UTC")
        by_source = await repository.usage_by_origin_and_operation(LlmCallFilter())

    assert [(e.day.isoformat(), e.model, e.totals.calls) for e in kolkata] == [
        ("2026-10-12", "claude-haiku-5-5", 2),
        ("2026-10-12", "claude-sonnet-5-5", 1),
    ]
    assert [(e.day.isoformat(), e.model, e.totals.calls) for e in utc] == [
        ("2026-10-11", "claude-haiku-5-5", 1),
        ("2026-10-12", "claude-haiku-5-5", 1),
        ("2026-10-12", "claude-sonnet-5-5", 1),
    ]
    haiku_day = kolkata[0].totals
    assert haiku_day.input_tokens == 20_000
    assert haiku_day.estimated_cost_usd == Decimal("0.003000")
    assert haiku_day.average_duration_ms == 100
    assert [(e.origin, e.operation, e.totals.calls) for e in by_source] == [
        (LlmCallOrigin.OTHER, LlmOperation.EXTRACTION, 3)
    ]


async def test_latency_percentiles_count_successful_calls_only(
    session_factory: SessionFactory,
) -> None:
    log = LlmCallLog(session_factory)
    for duration in (100, 200, 300):
        await log.record(make_record(duration_ms=duration))
    await log.record(make_record(duration_ms=5000, status=LlmCallStatus.FAILED))

    async with session_factory() as session:
        latency = await LlmCallRepository(session).latency(LlmCallFilter())
        nothing = await LlmCallRepository(session).latency(LlmCallFilter(model="none"))

    assert (latency.p50_ms, latency.p95_ms) == (200.0, 290.0)
    assert (nothing.p50_ms, nothing.p95_ms) == (None, None)


async def test_failures_are_counted_by_error_code(session_factory: SessionFactory) -> None:
    log = LlmCallLog(session_factory)
    await log.record(make_record(status=LlmCallStatus.FAILED, started_at=T0))
    await log.record(make_record(status=LlmCallStatus.FAILED, started_at=T0 + timedelta(hours=1)))
    await log.record(
        make_record(status=LlmCallStatus.FAILED, error_code="EXTRACTION_PROVIDER_BILLING")
    )
    await log.record(make_record())

    async with session_factory() as session:
        errors = await LlmCallRepository(session).errors(LlmCallFilter())

    assert [(e.error_code, e.calls) for e in errors] == [
        ("EXTRACTION_TRANSIENT_FAILURE", 2),
        ("EXTRACTION_PROVIDER_BILLING", 1),
    ]
    assert errors[0].last_seen_at == T0 + timedelta(hours=1)


def test_totals_add_up() -> None:
    first = UsageTotals(
        calls=2,
        failed_calls=1,
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=Decimal("0.5"),
        unpriced_calls=1,
        duration_ms=300,
    )
    second = UsageTotals(calls=1, input_tokens=5, duration_ms=100)

    total = first + second

    assert (total.calls, total.failed_calls, total.input_tokens, total.output_tokens) == (
        3,
        1,
        15,
        5,
    )
    assert total.estimated_cost_usd == Decimal("0.5")
    assert total.unpriced_calls == 1
    assert total.average_duration_ms == pytest.approx(400 / 3)
    assert UsageTotals().average_duration_ms is None


# --- Constraints ----------------------------------------------------------------------


def row(**overrides: Any) -> LlmCall:
    values: dict[str, Any] = {
        "id": new_uuid(),
        "provider": "anthropic",
        "operation": "extraction",
        "origin": "other",
        "status": "succeeded",
        "requested_model": "claude-haiku-5-5",
        "started_at": T0,
        "duration_ms": 10,
    }
    values.update(overrides)
    return LlmCall(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"origin": "pipeline"}, id="pipeline call without a run"),
        pytest.param({"origin": "playground"}, id="playground call without a test"),
        pytest.param({"origin": "evaluation"}, id="evaluation call without a run"),
        pytest.param({"status": "failed"}, id="failure without an error code"),
        pytest.param({"error_code": "X"}, id="success with an error code"),
        pytest.param({"input_tokens": -1}, id="negative tokens"),
        pytest.param({"duration_ms": -1}, id="negative duration"),
        pytest.param({"estimated_cost_usd": Decimal("-1")}, id="negative cost"),
        pytest.param({"operation": "summarize"}, id="unknown operation"),
        pytest.param({"origin": "cron"}, id="unknown origin"),
    ],
)
async def test_the_log_rejects_inconsistent_rows(
    session_factory: SessionFactory, overrides: dict[str, Any]
) -> None:
    async with session_factory() as session:
        session.add(row(**overrides))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


# --- Links to pipeline runs -----------------------------------------------------------


async def test_the_pipeline_logs_its_extraction_call_against_the_run(
    make_harness: HarnessFactory, session_factory: SessionFactory, clock: FakeClock
) -> None:
    observer = AnthropicCallObserver(LlmCallLog(session_factory), clock=clock)
    harness = make_harness(LoggedScriptedExtractor(observer, extraction()))

    unit, outcome = await harness.ingest_and_process("buy milk")

    assert outcome.status is ProcessingStatus.SUCCEEDED
    (call,) = await stored_calls(session_factory, processing_run_id=unit.run.id)
    assert (call.origin, call.operation, call.status) == ("pipeline", "extraction", "succeeded")
    assert call.attempt_number == 1
    assert (call.input_tokens, call.output_tokens) == (100, 50)
    assert call.started_at == clock()
    assert call.request_id == "req_test_1"


async def test_every_attempt_of_a_run_is_logged(
    make_harness: HarnessFactory, session_factory: SessionFactory, clock: FakeClock
) -> None:
    observer = AnthropicCallObserver(LlmCallLog(session_factory), clock=clock)
    harness = make_harness(
        LoggedScriptedExtractor(observer, TransientExtractionError("busy"), extraction())
    )

    unit, first = await harness.ingest_and_process("buy milk")
    assert first.status is ProcessingStatus.QUEUED
    clock.advance(minutes=5)
    second = await harness.runner.process_run(unit.run.id)
    assert second.status is ProcessingStatus.SUCCEEDED

    calls = list(reversed(await stored_calls(session_factory, processing_run_id=unit.run.id)))
    assert [call.attempt_number for call in calls] == [1, 2]
    assert [call.status for call in calls] == ["failed", "succeeded"]
    assert [call.error_code for call in calls] == ["EXTRACTION_TRANSIENT_FAILURE", None]
