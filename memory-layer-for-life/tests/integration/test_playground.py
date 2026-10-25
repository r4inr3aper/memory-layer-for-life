"""Single test calls: what is sent, what is kept, and how failures are reported."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import new_uuid
from app.domain.enums import LlmCallOrigin, MemoryState, MemoryType
from app.domain.errors import (
    ExtractionBillingError,
    InvalidProcessingUnitError,
    ProviderNotConfiguredError,
    RecordNotFoundError,
    UnsupportedModelError,
)
from app.integrations.anthropic_calls import AnthropicCallObserver
from app.integrations.extraction.base import Extractor
from app.integrations.extraction.factory import FixedExtractorFactory
from app.integrations.llm_calls import LlmCallContext
from app.repositories.playground_repository import PlaygroundRepository
from app.services.llm_call_log import LlmCallLog
from app.services.playground import PlaygroundLimits, PlaygroundMessage, PlaygroundService
from tests.support.call_log import LoggedScriptedExtractor
from tests.support.extraction import ScriptedExtractor, evidence, extraction, financial, memory
from tests.support.pipeline import FakeClock
from tests.unit.test_evaluation import expense

SessionFactory = async_sessionmaker[AsyncSession]

T0 = datetime(2026, 10, 12, 3, 30, tzinfo=UTC)  # 09:00 in Asia/Kolkata


def build_service(
    session_factory: SessionFactory, extractor: Extractor | None, clock: FakeClock
) -> PlaygroundService:
    return PlaygroundService(
        session_factory,
        FixedExtractorFactory(extractor),
        default_model="claude-sonnet-5-5",
        default_effort="medium",
        default_timezone="Asia/Kolkata",
        limits=PlaygroundLimits(max_messages=3, max_content_chars=40),
        clock=clock,
    )


async def test_a_test_call_keeps_what_was_sent_and_what_came_back(
    session_factory: SessionFactory, clock: FakeClock
) -> None:
    extractor = ScriptedExtractor(expense())
    service = build_service(session_factory, extractor, clock)

    result = await service.run([PlaygroundMessage("500 petrol", sent_at=T0)])

    run = result.run
    assert run.status == "succeeded"
    assert run.messages == [{"index": 0, "text": "500 petrol", "sent_at": T0.isoformat()}]
    assert (run.timezone_name, run.requested_model, run.effort) == (
        "Asia/Kolkata",
        "claude-sonnet-5-5",
        "medium",
    )
    assert run.output is not None
    assert run.output["disposition"] == "extract"
    assert run.output["memories"][0]["financial"]["amount"] == 500
    assert run.corrections == []
    assert run.error_code is None
    assert run.finished_at == clock()
    # The scripted extractor makes no provider call, so there is nothing in the log.
    assert result.call is None
    # The model saw the note exactly as the pipeline would present it.
    (request,) = extractor.requests
    assert request.messages[0].text == "500 petrol"
    assert request.messages[0].sent_at_local == datetime(2026, 10, 12, 9, 0)
    assert request.timezone_name == "Asia/Kolkata"
    assert request.call_context == LlmCallContext(
        origin=LlmCallOrigin.PLAYGROUND, playground_run_id=run.id
    )
    assert (await service.get(run.id)).run.id == run.id


async def test_the_call_a_test_makes_is_logged_and_returned_with_it(
    session_factory: SessionFactory, clock: FakeClock
) -> None:
    observer = AnthropicCallObserver(LlmCallLog(session_factory), clock=clock)
    service = build_service(session_factory, LoggedScriptedExtractor(observer, expense()), clock)

    result = await service.run([PlaygroundMessage("500 petrol")])

    assert result.call is not None
    assert result.call.playground_run_id == result.run.id
    assert (result.call.origin, result.call.status) == ("playground", "succeeded")
    assert (await service.get(result.run.id)).call is not None


async def test_the_pipeline_checks_are_applied_to_a_test_call(
    session_factory: SessionFactory, clock: FakeClock
) -> None:
    """A written calculation is recomputed, exactly as when a note is captured."""
    miscalculated = extraction(
        memory(
            "Sum of 245+131+200+135",
            memory_type=MemoryType.FINANCIAL_NOTE,
            state=MemoryState.NOT_APPLICABLE,
            evidence_refs=[evidence(0, "245+131+200+135")],
            financial=financial(611, calculation="245+131+200+135"),
        )
    )
    service = build_service(session_factory, ScriptedExtractor(miscalculated), clock)

    result = await service.run([PlaygroundMessage("245+131+200+135")])

    assert result.run.output is not None
    assert result.run.output["memories"][0]["financial"]["amount"] == 711
    assert result.run.corrections == ["memory 0: amount recomputed from the written calculation"]


async def test_an_answer_that_fails_the_checks_is_a_failed_test_not_an_error(
    session_factory: SessionFactory, clock: FakeClock
) -> None:
    pointing_nowhere = extraction(memory(evidence_refs=[evidence(3, "nowhere")]))
    service = build_service(session_factory, ScriptedExtractor(pointing_nowhere), clock)

    result = await service.run([PlaygroundMessage("buy milk")])

    assert result.run.status == "failed"
    assert result.run.error_code == "EXTRACTION_OUTPUT_INVALID"
    assert "cites message 3" in (result.run.error_message or "")
    assert result.run.output is None
    assert result.run.finished_at == clock()


async def test_a_provider_failure_is_a_failed_test(
    session_factory: SessionFactory, clock: FakeClock
) -> None:
    service = build_service(
        session_factory, ScriptedExtractor(ExtractionBillingError("no credit")), clock
    )

    result = await service.run([PlaygroundMessage("buy milk")])

    assert result.run.status == "failed"
    assert (result.run.error_code, result.run.error_message) == (
        "EXTRACTION_PROVIDER_BILLING",
        "no credit",
    )


async def test_an_unexpected_failure_is_recorded_and_then_raised(
    session_factory: SessionFactory, clock: FakeClock
) -> None:
    service = build_service(session_factory, ScriptedExtractor(RuntimeError("boom")), clock)

    with pytest.raises(RuntimeError):
        await service.run([PlaygroundMessage("buy milk")])

    async with session_factory() as session:
        runs, total = await PlaygroundRepository(session).list_runs(limit=10, offset=0)
    assert total == 1
    assert runs[0].status == "failed"
    assert (runs[0].error_code, runs[0].error_message) == (
        "UNEXPECTED_ERROR",
        "Unexpected RuntimeError.",
    )


@pytest.mark.parametrize(
    "messages",
    [
        pytest.param([], id="no message"),
        pytest.param([PlaygroundMessage("   ")], id="blank message"),
        pytest.param([PlaygroundMessage("x" * 41)], id="message too long"),
        pytest.param([PlaygroundMessage("a")] * 4, id="too many messages"),
    ],
)
async def test_limits_are_enforced_before_any_call(
    session_factory: SessionFactory, clock: FakeClock, messages: list[PlaygroundMessage]
) -> None:
    extractor = ScriptedExtractor(expense())
    service = build_service(session_factory, extractor, clock)

    with pytest.raises(InvalidProcessingUnitError):
        await service.run(messages)

    assert extractor.call_count == 0


async def test_only_offered_models_can_be_tested(
    session_factory: SessionFactory, clock: FakeClock
) -> None:
    service = build_service(session_factory, ScriptedExtractor(expense()), clock)

    with pytest.raises(UnsupportedModelError):
        await service.run([PlaygroundMessage("buy milk")], model="gpt-9")
    chosen = await service.run([PlaygroundMessage("buy milk")], model="claude-haiku-5-5")

    assert chosen.run.requested_model == "claude-haiku-5-5"


async def test_a_test_needs_a_configured_provider(
    session_factory: SessionFactory, clock: FakeClock
) -> None:
    service = build_service(session_factory, None, clock)

    assert service.available is False
    with pytest.raises(ProviderNotConfiguredError):
        await service.run([PlaygroundMessage("buy milk")])


async def test_an_unknown_test_is_not_found(
    session_factory: SessionFactory, clock: FakeClock
) -> None:
    service = build_service(session_factory, ScriptedExtractor(expense()), clock)

    with pytest.raises(RecordNotFoundError):
        await service.get(new_uuid())


def test_messages_carry_only_text_and_time() -> None:
    message: Any = PlaygroundMessage("buy milk")

    assert (message.text, message.sent_at) == ("buy milk", None)
