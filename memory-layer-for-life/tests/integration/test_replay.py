"""Replay: no duplicate effects for the same version, preserved history for a new one."""

import uuid

from app.domain.enums import ProcessingStatus, ReplayAction
from app.domain.errors import (
    InvalidExtractionOutputError,
    PermanentExtractionError,
)
from app.domain.versions import ExtractorDescriptor
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from app.models.memory_source import MemorySource
from app.models.processing_run import ProcessingRun
from app.models.processing_run_message import ProcessingRunMessage
from app.models.raw_message import RawMessage
from tests.integration.conftest import HarnessFactory
from tests.support.extraction import ScriptedExtractor, abstention, extraction, memory

NEXT_PROMPT = ExtractorDescriptor(provider="scripted", model="test-model", prompt_version="2")


async def test_replaying_the_same_version_has_no_effect(make_harness: HarnessFactory) -> None:
    extractor = ScriptedExtractor()
    harness = make_harness(extractor)
    unit, _ = await harness.ingest_and_process("buy milk", source_ids=["evt-1"])

    (outcome,) = await harness.replay.replay(raw_message_ids=[unit.messages[0].id], limit=10)

    assert outcome.action is ReplayAction.UNCHANGED
    assert outcome.run.id == unit.run.id
    assert outcome.run.status is ProcessingStatus.SUCCEEDED
    assert (await harness.runner.process_run(unit.run.id)).status is None
    assert extractor.call_count == 1
    assert await harness.count(ProcessingRun) == 1
    assert await harness.count(Memory) == 1
    assert await harness.count(MemorySource) == 1
    assert await harness.count(RawMessage) == 1


async def test_a_new_version_gets_a_new_run_and_keeps_history(make_harness: HarnessFactory) -> None:
    old = make_harness(ScriptedExtractor(extraction(memory("Old reading"))))
    unit, _ = await old.ingest_and_process("buy milk", "2 litres")
    (old_memory,) = await old.rows(Memory)
    (old_result,) = await old.rows(ExtractionResult)

    new = make_harness(ScriptedExtractor(extraction(memory("New reading")), descriptor=NEXT_PROMPT))
    (outcome,) = await new.replay.replay(raw_message_ids=[unit.messages[0].id], limit=10)

    assert outcome.action is ReplayAction.CREATED
    assert outcome.run.id != unit.run.id
    assert outcome.run.status is ProcessingStatus.QUEUED
    # The unit is the same messages in the same order. No message was created.
    assert list(outcome.run.raw_message_ids) == [message.id for message in unit.messages]
    assert await new.count(RawMessage) == 2

    assert (await new.runner.process_run(outcome.run.id)).status is ProcessingStatus.SUCCEEDED

    memories = {item.content: item for item in await new.rows(Memory)}
    assert set(memories) == {"Old reading", "New reading"}
    # The old run and everything it produced are exactly as they were.
    assert memories["Old reading"].id == old_memory.id
    assert memories["Old reading"].updated_at == old_memory.updated_at
    assert memories["Old reading"].origin_extraction_result_id == old_result.id
    old_run = await new.get_run(unit.run.id)
    assert old_run.status == ProcessingStatus.SUCCEEDED
    assert await new.count(ExtractionResult) == 2
    # Every memory is still traceable to both messages through its own extraction result.
    sources = await new.rows(MemorySource)
    assert len(sources) == 4
    assert {source.extraction_result_id for source in sources} == {
        item.origin_extraction_result_id for item in memories.values()
    }
    # Both versions stay proposed: choosing between them is an explicit later step.
    assert {item.status for item in memories.values()} == {"proposed"}


async def test_replaying_a_new_version_twice_creates_one_run(make_harness: HarnessFactory) -> None:
    old = make_harness(ScriptedExtractor())
    unit, _ = await old.ingest_and_process("buy milk")
    new = make_harness(ScriptedExtractor(descriptor=NEXT_PROMPT))

    (first,) = await new.replay.replay(run_ids=[unit.run.id], limit=10)
    (second,) = await new.replay.replay(run_ids=[unit.run.id], limit=10)

    assert first.action is ReplayAction.CREATED
    assert second.action is ReplayAction.UNCHANGED
    assert second.run.id == first.run.id
    assert await new.count(ProcessingRun) == 2


async def test_a_failed_run_is_requeued(make_harness: HarnessFactory) -> None:
    extractor = ScriptedExtractor(PermanentExtractionError("rejected"), extraction())
    harness = make_harness(extractor)
    unit, failed = await harness.ingest_and_process("buy milk")
    assert failed.status is ProcessingStatus.FAILED

    (outcome,) = await harness.replay.replay(run_ids=[unit.run.id], limit=10)

    assert outcome.action is ReplayAction.REQUEUED
    assert outcome.run.id == unit.run.id
    assert outcome.run.status is ProcessingStatus.QUEUED
    assert (await harness.runner.process_run(unit.run.id)).status is ProcessingStatus.SUCCEEDED
    run = await harness.get_run(unit.run.id)
    assert run.attempt_number == 2
    assert run.error_code is None
    assert await harness.event_types(run.id) == [
        "queued",
        "claimed",
        "failed",
        "requeued",
        "claimed",
        "extraction_stored",
        "succeeded",
    ]


async def test_a_run_in_review_with_a_stored_result_is_left_alone(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(ScriptedExtractor(abstention()))
    unit, _ = await harness.ingest_and_process("14 15")

    (outcome,) = await harness.replay.replay(run_ids=[unit.run.id], limit=10)

    assert outcome.action is ReplayAction.UNCHANGED
    assert outcome.run.status is ProcessingStatus.NEEDS_REVIEW


async def test_a_run_in_review_without_a_stored_result_is_requeued(
    make_harness: HarnessFactory,
) -> None:
    extractor = ScriptedExtractor(InvalidExtractionOutputError("bad output"), extraction())
    harness = make_harness(extractor)
    unit, _ = await harness.ingest_and_process("buy milk")

    (outcome,) = await harness.replay.replay(run_ids=[unit.run.id], limit=10)

    assert outcome.action is ReplayAction.REQUEUED
    assert (await harness.runner.process_run(unit.run.id)).status is ProcessingStatus.SUCCEEDED
    assert await harness.count(Memory) == 1


async def test_a_queued_run_is_left_alone(make_harness: HarnessFactory) -> None:
    harness = make_harness(ScriptedExtractor())
    unit = await harness.ingest("buy milk")

    (outcome,) = await harness.replay.replay(run_ids=[unit.run.id], limit=10)

    assert outcome.action is ReplayAction.UNCHANGED
    assert await harness.event_types(unit.run.id) == ["queued"]


async def test_replay_by_message_selects_every_unit_containing_it(
    make_harness: HarnessFactory,
) -> None:
    old = make_harness(ScriptedExtractor())
    alone = await old.ingest("250", source_ids=["evt-1"])
    paired = await old.ingest("250", "Jeera", source_ids=["evt-1", "evt-2"])
    await old.ingest("unrelated", source_ids=["evt-3"])
    new = make_harness(ScriptedExtractor(descriptor=NEXT_PROMPT))

    outcomes = await new.replay.replay(raw_message_ids=[alone.messages[0].id], limit=10)

    assert [outcome.action for outcome in outcomes] == [ReplayAction.CREATED] * 2
    assert [list(outcome.run.raw_message_ids) for outcome in outcomes] == [
        [alone.messages[0].id],
        [message.id for message in paired.messages],
    ]


async def test_batch_replay_covers_all_units_up_to_the_limit(make_harness: HarnessFactory) -> None:
    old = make_harness(ScriptedExtractor())
    for number in range(5):
        await old.ingest(f"note {number}")
    new = make_harness(ScriptedExtractor(descriptor=NEXT_PROMPT))

    limited = await new.replay.replay(limit=3)
    assert [outcome.action for outcome in limited] == [ReplayAction.CREATED] * 3

    everything = await new.replay.replay(limit=100)
    assert len(everything) == 5
    assert [outcome.action for outcome in everything].count(ReplayAction.CREATED) == 2
    assert await new.count(ProcessingRun) == 10
    assert await new.count(RawMessage) == 5
    # Each unit appears once, even though it now has runs for two versions.
    assert len(await new.replay.replay(limit=100)) == 5


async def test_replay_keeps_the_unit_order_of_the_new_run(make_harness: HarnessFactory) -> None:
    old = make_harness(ScriptedExtractor())
    unit = await old.ingest("first", "second", "third")
    new = make_harness(ScriptedExtractor(descriptor=NEXT_PROMPT))

    (outcome,) = await new.replay.replay(run_ids=[unit.run.id], limit=10)

    links = [
        link
        for link in await new.rows(ProcessingRunMessage)
        if link.processing_run_id == outcome.run.id
    ]
    ordered = sorted(links, key=lambda link: link.position)
    assert [link.raw_message_id for link in ordered] == [message.id for message in unit.messages]


async def test_unknown_ids_select_nothing(make_harness: HarnessFactory) -> None:
    harness = make_harness(ScriptedExtractor())
    await harness.ingest("buy milk")

    assert await harness.replay.replay(raw_message_ids=[uuid.uuid4()], limit=10) == []
    assert await harness.replay.replay(run_ids=[uuid.uuid4()], limit=10) == []
    assert await harness.count(ProcessingRun) == 1
