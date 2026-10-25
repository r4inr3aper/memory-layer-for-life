"""The pipeline runner against PostgreSQL: results, state transitions, retries, recovery."""

import asyncio
from datetime import UTC, datetime, timedelta

from app.domain.enums import (
    ExtractionDisposition,
    ExtractionStatus,
    MemoryStatus,
    MemoryType,
    ProcessingStatus,
    SourceRole,
)
from app.domain.errors import (
    InvalidExtractionOutputError,
    PermanentExtractionError,
    TransientExtractionError,
)
from app.domain.run_state import RetryPolicy
from app.domain.versions import EXTRACTION_SCHEMA_VERSION
from app.integrations.extraction.base import ExtractionRequest, ExtractionResponse
from app.models.entity import Entity
from app.models.entity_mention import EntityMention
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from app.models.memory_source import MemorySource
from app.models.raw_message import RawMessage
from app.repositories.processing_run_repository import ProcessingRunRepository
from app.schemas.extraction import ExtractionPayload
from app.services.processing.memory_builder import MemoryBuilder
from tests.integration.conftest import HarnessFactory
from tests.support.extraction import (
    DEFAULT_DESCRIPTOR,
    ScriptedExtractor,
    abstention,
    evidence,
    extraction,
    memory,
    mention,
)
from tests.support.pipeline import FakeClock

# --- Successful runs ------------------------------------------------------------------


async def test_run_stores_a_proposed_memory_with_its_evidence(
    make_harness: HarnessFactory, clock: FakeClock
) -> None:
    extractor = ScriptedExtractor(
        extraction(memory("Buy milk", evidence_refs=[evidence(0, "buy milk")]))
    )
    harness = make_harness(extractor)

    unit, outcome = await harness.ingest_and_process("buy milk")

    assert outcome.status is ProcessingStatus.SUCCEEDED
    run = await harness.get_run(unit.run.id)
    assert run.status == ProcessingStatus.SUCCEEDED
    assert run.attempt_number == 1
    assert run.started_at == clock()
    assert run.finished_at == clock()
    assert run.error_code is None

    (stored,) = await harness.rows(Memory)
    assert stored.content == "Buy milk"
    assert stored.memory_type == MemoryType.TASK
    assert stored.status == MemoryStatus.PROPOSED
    assert stored.origin_ordinal == 0
    assert stored.metadata_["state"] == "open"
    assert stored.metadata_["disposition"] == ExtractionDisposition.EXTRACT

    (source,) = await harness.rows(MemorySource)
    assert source.memory_id == stored.id
    assert source.raw_message_id == unit.messages[0].id
    assert source.source_role == SourceRole.SUPPORTING
    assert source.evidence_text == "buy milk"

    (result,) = await harness.rows(ExtractionResult)
    assert result.processing_run_id == run.id
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.schema_version == EXTRACTION_SCHEMA_VERSION
    assert result.extractor_version == DEFAULT_DESCRIPTOR.version
    assert result.model_name == DEFAULT_DESCRIPTOR.model
    assert result.metadata_["usage"]["input_tokens"] == 100
    assert stored.origin_extraction_result_id == result.id
    payload = ExtractionPayload.model_validate(result.payload)
    assert payload.message_ids == [unit.messages[0].id]

    assert await harness.event_types(run.id) == [
        "queued",
        "claimed",
        "extraction_stored",
        "succeeded",
    ]


async def test_every_message_of_a_unit_is_linked_to_the_memory(
    make_harness: HarnessFactory,
) -> None:
    extractor = ScriptedExtractor(
        extraction(
            memory(
                "Groceries cost 336",
                memory_type=MemoryType.FINANCIAL_NOTE,
                evidence_refs=[evidence(0, "232+104"), evidence(1, "rice, dal")],
            )
        )
    )
    harness = make_harness(extractor)

    unit, outcome = await harness.ingest_and_process("232+104 groceries", "rice, dal", "for dinner")

    assert outcome.status is ProcessingStatus.SUCCEEDED
    sources = {source.raw_message_id: source for source in await harness.rows(MemorySource)}
    first, second, third = (sources[message.id] for message in unit.messages)
    assert (first.source_role, first.evidence_text) == (SourceRole.SUPPORTING, "232+104")
    assert (second.source_role, second.evidence_text) == (SourceRole.SUPPORTING, "rice, dal")
    # The third message was read with the others but is not cited as evidence.
    assert (third.source_role, third.evidence_text) == (SourceRole.CONTEXTUAL, None)


async def test_a_quote_that_is_not_in_the_message_is_not_stored_as_evidence(
    make_harness: HarnessFactory,
) -> None:
    extractor = ScriptedExtractor(
        extraction(memory("Buy milk", evidence_refs=[evidence(0, "purchase some dairy")]))
    )
    harness = make_harness(extractor)

    await harness.ingest_and_process("buy milk")

    (source,) = await harness.rows(MemorySource)
    assert source.source_role == SourceRole.SUPPORTING
    assert source.evidence_text is None


async def test_one_unit_can_yield_several_memories(make_harness: HarnessFactory) -> None:
    extractor = ScriptedExtractor(
        extraction(
            memory("Saturday: study asyncio", memory_type=MemoryType.PLAN),
            memory("Sunday: update resume", memory_type=MemoryType.PLAN),
        )
    )
    harness = make_harness(extractor)

    await harness.ingest_and_process("buy milk")

    memories = sorted(await harness.rows(Memory), key=lambda item: item.origin_ordinal)
    assert [item.content for item in memories] == [
        "Saturday: study asyncio",
        "Sunday: update resume",
    ]
    assert [item.origin_ordinal for item in memories] == [0, 1]


async def test_extractor_receives_normalized_text_and_local_time(
    make_harness: HarnessFactory,
) -> None:
    extractor = ScriptedExtractor()
    harness = make_harness(extractor, timezone_name="Asia/Kolkata")
    narrow_no_break_space = chr(0x202F)

    await harness.ingest_and_process(
        f"buy{narrow_no_break_space}milk  \r\n",
        sent_at=datetime(2026, 4, 18, 21, 57, tzinfo=UTC),
    )

    (request,) = extractor.requests
    (message,) = request.messages
    assert message.text == "buy milk"
    # 21:57 UTC is 03:27 the next day in India.
    assert message.sent_at_local == datetime(2026, 4, 19, 3, 27)
    assert request.timezone_name == "Asia/Kolkata"
    # The stored evidence keeps its original bytes.
    (stored,) = await harness.rows(RawMessage)
    assert stored.content == f"buy{narrow_no_break_space}milk  \r\n"


# --- Abstention and rejected output ---------------------------------------------------


async def test_abstention_sends_the_run_to_review_without_memories(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(ScriptedExtractor(abstention()))

    unit, outcome = await harness.ingest_and_process("14 15")

    assert outcome.status is ProcessingStatus.NEEDS_REVIEW
    run = await harness.get_run(unit.run.id)
    assert run.status == ProcessingStatus.NEEDS_REVIEW
    assert run.finished_at is not None
    (result,) = await harness.rows(ExtractionResult)
    assert result.status == ExtractionStatus.NEEDS_REVIEW
    assert await harness.count(Memory) == 0
    assert await harness.count(RawMessage) == 1
    assert await harness.event_types(run.id) == [
        "queued",
        "claimed",
        "extraction_stored",
        "needs_review",
    ]


async def test_invalid_extractor_output_goes_to_review_and_stores_nothing(
    make_harness: HarnessFactory,
) -> None:
    extractor = ScriptedExtractor(InvalidExtractionOutputError("1 validation error(s)"))
    harness = make_harness(extractor)

    unit, outcome = await harness.ingest_and_process("buy milk")

    assert outcome.status is ProcessingStatus.NEEDS_REVIEW
    run = await harness.get_run(unit.run.id)
    assert run.error_code == InvalidExtractionOutputError.code
    assert await harness.count(ExtractionResult) == 0
    assert await harness.count(Memory) == 0
    assert extractor.call_count == 1


async def test_evidence_pointing_outside_the_unit_is_rejected(make_harness: HarnessFactory) -> None:
    extractor = ScriptedExtractor(
        extraction(memory("Buy milk", evidence_refs=[evidence(3, "buy milk")]))
    )
    harness = make_harness(extractor)

    unit, outcome = await harness.ingest_and_process("buy milk")

    assert outcome.status is ProcessingStatus.NEEDS_REVIEW
    run = await harness.get_run(unit.run.id)
    assert run.error_code == InvalidExtractionOutputError.code
    assert await harness.count(ExtractionResult) == 0
    assert await harness.count(Memory) == 0


# --- Failures and retries -------------------------------------------------------------


async def test_transient_failure_is_retried_after_backoff(
    make_harness: HarnessFactory, clock: FakeClock
) -> None:
    extractor = ScriptedExtractor(TransientExtractionError("rate limited"), extraction())
    harness = make_harness(extractor)

    unit, first = await harness.ingest_and_process("buy milk")

    assert first.status is ProcessingStatus.QUEUED
    run = await harness.get_run(unit.run.id)
    assert run.status == ProcessingStatus.QUEUED
    assert run.error_code == TransientExtractionError.code
    assert run.available_at == clock() + timedelta(seconds=30)

    # Not due yet: nothing happens.
    assert (await harness.runner.process_run(run.id)).status is None
    assert extractor.call_count == 1

    clock.advance(seconds=30)
    second = await harness.runner.process_run(run.id)

    assert second.status is ProcessingStatus.SUCCEEDED
    run = await harness.get_run(unit.run.id)
    assert run.attempt_number == 2
    assert run.error_code is None
    assert extractor.call_count == 2
    assert await harness.count(Memory) == 1
    assert await harness.event_types(run.id) == [
        "queued",
        "claimed",
        "retry_scheduled",
        "claimed",
        "extraction_stored",
        "succeeded",
    ]


async def test_transient_failures_stop_after_the_last_allowed_attempt(
    make_harness: HarnessFactory, clock: FakeClock
) -> None:
    extractor = ScriptedExtractor(TransientExtractionError("unavailable"))
    harness = make_harness(
        extractor, retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=10)
    )

    unit = await harness.ingest("buy milk")
    statuses = []
    for _ in range(5):
        statuses.append((await harness.runner.process_run(unit.run.id)).status)
        clock.advance(hours=1)

    assert statuses == [
        ProcessingStatus.QUEUED,
        ProcessingStatus.QUEUED,
        ProcessingStatus.FAILED,
        None,
        None,
    ]
    run = await harness.get_run(unit.run.id)
    assert run.status == ProcessingStatus.FAILED
    assert run.attempt_number == 3
    assert run.finished_at is not None
    assert extractor.call_count == 3
    # The input is still there, untouched.
    (stored,) = await harness.rows(RawMessage)
    assert stored.content == "buy milk"


async def test_permanent_failure_is_not_retried(make_harness: HarnessFactory) -> None:
    extractor = ScriptedExtractor(PermanentExtractionError("rejected credentials"))
    harness = make_harness(extractor)

    unit, outcome = await harness.ingest_and_process("buy milk")

    assert outcome.status is ProcessingStatus.FAILED
    run = await harness.get_run(unit.run.id)
    assert run.status == ProcessingStatus.FAILED
    assert run.error_code == PermanentExtractionError.code
    assert run.error_message == "rejected credentials"
    assert extractor.call_count == 1
    assert await harness.event_types(run.id) == ["queued", "claimed", "failed"]


async def test_failure_after_extraction_reuses_the_stored_result_on_retry(
    make_harness: HarnessFactory, clock: FakeClock, monkeypatch
) -> None:
    extractor = ScriptedExtractor(
        extraction(memory("Call Asha", mention_indexes=[0]), mentions=[mention("Asha")])
    )
    harness = make_harness(extractor)
    real_build = MemoryBuilder.build
    calls = {"count": 0}

    def fail_once(self: MemoryBuilder, *args: object, **kwargs: object) -> object:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated crash while constructing memories")
        return real_build(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(MemoryBuilder, "build", fail_once)

    unit, first = await harness.ingest_and_process("call Asha")

    assert first.status is ProcessingStatus.QUEUED
    run = await harness.get_run(unit.run.id)
    assert run.error_code == "UNEXPECTED_ERROR"
    assert "RuntimeError" in (run.error_message or "")
    # The extraction result survived. Everything built after it was rolled back together.
    assert await harness.count(ExtractionResult) == 1
    assert await harness.count(Entity) == 0
    assert await harness.count(EntityMention) == 0
    assert await harness.count(Memory) == 0

    clock.advance(minutes=1)
    second = await harness.runner.process_run(run.id)

    assert second.status is ProcessingStatus.SUCCEEDED
    assert extractor.call_count == 1, "the model must not be called again"
    assert await harness.count(ExtractionResult) == 1
    assert await harness.count(Memory) == 1
    assert await harness.count(Entity) == 1
    assert "extraction_reused" in await harness.event_types(run.id)


async def test_a_finished_run_is_never_executed_again(make_harness: HarnessFactory) -> None:
    extractor = ScriptedExtractor()
    harness = make_harness(extractor)

    unit, _ = await harness.ingest_and_process("buy milk")
    again = await harness.runner.process_run(unit.run.id)

    assert again.status is None
    assert extractor.call_count == 1
    assert await harness.count(Memory) == 1
    assert await harness.count(MemorySource) == 1


async def test_without_an_extractor_runs_stay_queued(make_harness: HarnessFactory) -> None:
    harness = make_harness(None)

    unit, outcome = await harness.ingest_and_process("buy milk")

    assert harness.runner.can_process is False
    assert outcome.status is None
    run = await harness.get_run(unit.run.id)
    assert run.status == ProcessingStatus.QUEUED
    assert run.started_at is None
    assert await harness.event_types(run.id) == ["queued"]
    assert await harness.runner.process_available(limit=10) == []


# --- Queue ----------------------------------------------------------------------------


async def test_process_available_takes_due_runs_oldest_first(
    make_harness: HarnessFactory, clock: FakeClock
) -> None:
    harness = make_harness(ScriptedExtractor())
    first = await harness.ingest("one")
    clock.advance(seconds=1)
    second = await harness.ingest("two")
    clock.advance(seconds=1)
    third = await harness.ingest("three")

    outcomes = await harness.runner.process_available(limit=2)

    assert [outcome.run_id for outcome in outcomes] == [first.run.id, second.run.id]
    assert all(outcome.status is ProcessingStatus.SUCCEEDED for outcome in outcomes)
    assert (await harness.get_run(third.run.id)).status == ProcessingStatus.QUEUED


async def test_process_available_leaves_runs_whose_backoff_has_not_elapsed(
    make_harness: HarnessFactory, clock: FakeClock
) -> None:
    extractor = ScriptedExtractor(TransientExtractionError("busy"), extraction())
    harness = make_harness(extractor)
    await harness.ingest_and_process("buy milk")

    assert await harness.runner.process_available(limit=10) == []

    clock.advance(seconds=30)
    (outcome,) = await harness.runner.process_available(limit=10)
    assert outcome.status is ProcessingStatus.SUCCEEDED


# --- Crash recovery and concurrency ---------------------------------------------------


async def _claim_without_executing(harness, run_id) -> None:  # type: ignore[no-untyped-def]
    """Put a run into ``running`` as a worker that then disappears."""
    async with harness.session_factory() as session, session.begin():
        claimed = await ProcessingRunRepository(session).claim(run_id, now=harness.clock())
        assert claimed is not None


async def test_a_run_abandoned_by_its_worker_is_recovered(
    make_harness: HarnessFactory, clock: FakeClock
) -> None:
    harness = make_harness(ScriptedExtractor(), lease=timedelta(minutes=10))
    unit = await harness.ingest("buy milk")
    await _claim_without_executing(harness, unit.run.id)

    clock.advance(minutes=9)
    assert await harness.runner.recover_expired_leases() == 0

    clock.advance(minutes=2)
    assert await harness.runner.recover_expired_leases() == 1
    run = await harness.get_run(unit.run.id)
    assert run.status == ProcessingStatus.QUEUED

    outcome = await harness.runner.process_run(run.id)
    assert outcome.status is ProcessingStatus.SUCCEEDED
    run = await harness.get_run(unit.run.id)
    assert run.attempt_number == 2
    assert "lease_expired" in await harness.event_types(run.id)


async def test_a_run_abandoned_on_its_last_attempt_fails(
    make_harness: HarnessFactory, clock: FakeClock
) -> None:
    harness = make_harness(
        ScriptedExtractor(),
        lease=timedelta(minutes=10),
        retry_policy=RetryPolicy(max_attempts=1),
    )
    unit = await harness.ingest("buy milk")
    await _claim_without_executing(harness, unit.run.id)

    clock.advance(minutes=11)
    assert await harness.runner.recover_expired_leases() == 1

    run = await harness.get_run(unit.run.id)
    assert run.status == ProcessingStatus.FAILED
    assert run.error_code == "LEASE_EXPIRED"
    assert await harness.event_types(run.id) == ["queued", "lease_expired", "failed"]


async def test_a_worker_that_lost_its_claim_cannot_write(
    make_harness: HarnessFactory, clock: FakeClock
) -> None:
    """A slow worker's lease expires and another worker finishes the run.

    When the slow worker finally gets its answer, it must notice and write nothing.
    """
    rescuer = make_harness(ScriptedExtractor(extraction(memory("Written by the rescuer"))))

    class SlowExtractor(ScriptedExtractor):
        async def extract(self, request: ExtractionRequest) -> ExtractionResponse:
            # While this call is in flight, the lease expires and the rescuer takes over.
            clock.advance(minutes=11)
            assert await rescuer.runner.recover_expired_leases() == 1
            rescue = await rescuer.runner.process_run(unit.run.id)
            assert rescue.status is ProcessingStatus.SUCCEEDED
            return await super().extract(request)

    slow = make_harness(SlowExtractor(extraction(memory("Written by the slow worker"))))
    unit = await slow.ingest("buy milk")

    outcome = await slow.runner.process_run(unit.run.id)

    assert outcome.status is None
    (stored,) = await slow.rows(Memory)
    assert stored.content == "Written by the rescuer"
    assert await slow.count(ExtractionResult) == 1
    run = await slow.get_run(unit.run.id)
    assert run.status == ProcessingStatus.SUCCEEDED
    assert run.attempt_number == 2


async def test_concurrent_workers_execute_a_run_exactly_once(make_harness: HarnessFactory) -> None:
    class YieldingExtractor(ScriptedExtractor):
        async def extract(self, request: ExtractionRequest) -> ExtractionResponse:
            await asyncio.sleep(0.05)
            return await super().extract(request)

    extractor = YieldingExtractor()
    harness = make_harness(extractor)
    unit = await harness.ingest("buy milk")

    outcomes = await asyncio.gather(*(harness.runner.process_run(unit.run.id) for _ in range(5)))

    statuses = [outcome.status for outcome in outcomes]
    assert statuses.count(ProcessingStatus.SUCCEEDED) == 1
    assert statuses.count(None) == 4
    assert extractor.call_count == 1
    assert await harness.count(Memory) == 1
    assert await harness.count(ExtractionResult) == 1


async def test_a_worker_that_lost_its_claim_cannot_record_a_failure(
    make_harness: HarnessFactory, clock: FakeClock
) -> None:
    """The slow worker fails after another worker has already finished the run."""
    rescuer = make_harness(ScriptedExtractor(extraction(memory("Written by the rescuer"))))

    class SlowFailingExtractor(ScriptedExtractor):
        async def extract(self, request: ExtractionRequest) -> ExtractionResponse:
            clock.advance(minutes=11)
            await rescuer.runner.recover_expired_leases()
            await rescuer.runner.process_run(unit.run.id)
            raise PermanentExtractionError("the slow worker's call failed")

    slow = make_harness(SlowFailingExtractor())
    unit = await slow.ingest("buy milk")

    outcome = await slow.runner.process_run(unit.run.id)

    assert outcome.status is None
    run = await slow.get_run(unit.run.id)
    # The rescuer's success stands. The stale failure was not written over it.
    assert run.status == ProcessingStatus.SUCCEEDED
    assert run.error_code is None
    assert "failed" not in await slow.event_types(run.id)
