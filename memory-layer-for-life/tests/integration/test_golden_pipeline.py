"""Every golden case through the real pipeline, on PostgreSQL, without a model.

The fixture extractor answers with what the dataset expects, so these tests are about
everything around the extractor: capture, persistence, provenance, entity resolution,
idempotency, and replay, exercised with the real shapes of real messages.
"""

from datetime import timedelta, timezone

import pytest

from app.domain.enums import (
    MemoryStatus,
    MentionResolutionStatus,
    MessageSource,
    ProcessingStatus,
    ReplayAction,
    SourceRole,
)
from app.domain.versions import ExtractorDescriptor
from app.models.entity import Entity
from app.models.entity_mention import EntityMention
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from app.models.memory_source import MemorySource
from app.models.processing_run import ProcessingRun
from app.models.raw_message import RawMessage
from app.schemas.extraction import ExtractionPayload
from app.schemas.memory_metadata import MemoryMetadata
from app.schemas.raw_message import RawMessageCreate
from evaluation.fixture_extractor import GoldenFixtureExtractor
from evaluation.golden import GoldenCase
from evaluation.scoring import score_case
from tests.integration.conftest import HarnessFactory
from tests.support.golden import golden_case_params, ideal_verdicts, require_golden_cases
from tests.support.pipeline import PipelineHarness

# The dataset's timestamps are local times of its author, who writes from India.
INDIA = timezone(timedelta(hours=5, minutes=30))
TIMEZONE_NAME = "Asia/Kolkata"


def unit_of(case: GoldenCase) -> list[RawMessageCreate]:
    return [
        RawMessageCreate(
            source=MessageSource.WHATSAPP_IMPORT,
            content=message.content,
            source_message_id=message.event_id,
            source_created_at=message.sent_at_local.replace(tzinfo=INDIA),
        )
        for message in case.input.messages
    ]


@pytest.mark.parametrize("case", golden_case_params())
async def test_golden_case_through_the_pipeline(
    case: GoldenCase, make_harness: HarnessFactory
) -> None:
    extractor = GoldenFixtureExtractor(require_golden_cases())
    harness = make_harness(extractor, timezone_name=TIMEZONE_NAME)
    expected_output = extractor.expected_output(case)

    (unit,) = await harness.ingestion.ingest([unit_of(case)])
    outcome = await harness.runner.process_run(unit.run.id)

    # The extractor saw each message at the local time the author wrote it.
    (request,) = extractor.requests
    assert [message.sent_at_local for message in request.messages] == [
        message.sent_at_local for message in case.input.messages
    ]

    # Evidence is stored exactly as written.
    stored_messages = {message.id: message for message in await harness.rows(RawMessage)}
    assert [stored_messages[item.id].content for item in unit.messages] == [
        message.content for message in case.input.messages
    ]

    (result,) = await harness.rows(ExtractionResult)
    payload = ExtractionPayload.model_validate(result.payload)
    assert payload.output == expected_output
    assert payload.message_ids == [item.id for item in unit.messages]

    memories = sorted(await harness.rows(Memory), key=lambda memory: memory.origin_ordinal)
    sources = await harness.rows(MemorySource)

    if case.expects_abstention:
        assert outcome.status is ProcessingStatus.NEEDS_REVIEW
        assert memories == []
        assert sources == []
        assert await harness.count(Entity) == 0
    else:
        assert outcome.status is ProcessingStatus.SUCCEEDED
        assert [memory.content for memory in memories] == [
            extracted.content for extracted in expected_output.memories
        ]
        assert {memory.status for memory in memories} == {MemoryStatus.PROPOSED}
        for memory, extracted in zip(memories, expected_output.memories, strict=True):
            metadata = MemoryMetadata.model_validate(memory.metadata_)
            assert metadata.disposition is case.expected.outcome
            assert metadata.financial == extracted.financial
            assert metadata.ambiguity == extracted.ambiguity
            assert memory.origin_extraction_result_id == result.id

            # Every memory is traceable to every message of its unit, with a quote that
            # was verified against the stored text.
            own_sources = [source for source in sources if source.memory_id == memory.id]
            assert {source.raw_message_id for source in own_sources} == set(stored_messages)
            for source in own_sources:
                assert source.source_role == SourceRole.SUPPORTING
                assert source.evidence_text
                assert source.evidence_text in stored_messages[source.raw_message_id].content

        mentions = await harness.rows(EntityMention)
        assert len(mentions) == len(expected_output.entity_mentions)
        for stored_mention in mentions:
            assert stored_mention.resolution_status == MentionResolutionStatus.RESOLVED
            message_text = stored_messages[stored_mention.raw_message_id].content
            assert (
                message_text[stored_mention.start_offset : stored_mention.end_offset]
                == stored_mention.mention_text
            )

    # What was stored still satisfies the scorer, read back from the database.
    verdicts = None if case.expects_abstention else ideal_verdicts(case, payload.output, extractor)
    assert score_case(case, payload.output, verdicts).passed

    # Running everything again changes nothing.
    counts_before = await _counts(harness)
    (again,) = await harness.ingestion.ingest([unit_of(case)])
    assert again.run.id == unit.run.id
    assert again.run.created is False
    assert all(not message.created for message in again.messages)
    (replayed,) = await harness.replay.replay(run_ids=[unit.run.id], limit=10)
    assert replayed.action is ReplayAction.UNCHANGED
    assert (await harness.runner.process_run(unit.run.id)).status is None
    assert await harness.runner.process_available(limit=10) == []
    assert await _counts(harness) == counts_before
    assert len(extractor.requests) == 1


async def _counts(harness: PipelineHarness) -> dict[str, int]:
    return {
        model.__tablename__: await harness.count(model)
        for model in (
            RawMessage,
            ProcessingRun,
            ExtractionResult,
            Memory,
            MemorySource,
            Entity,
            EntityMention,
        )
    }


async def test_the_whole_dataset_is_processed_once_and_replays_cleanly(
    make_harness: HarnessFactory,
) -> None:
    cases = require_golden_cases()
    extractor = GoldenFixtureExtractor(cases)
    harness = make_harness(extractor, timezone_name=TIMEZONE_NAME)
    distinct_messages = {message.event_id for case in cases for message in case.input.messages}
    distinct_units = {case.unit_key for case in cases}
    abstaining_units = {case.unit_key for case in cases if case.expects_abstention}
    expected_memories = sum(
        len(extractor.expected_output(case).memories)
        for case in {case.unit_key: case for case in cases}.values()
    )

    # Ingested in several batches, as an importer would do.
    units = []
    for start in range(0, len(cases), 50):
        units += await harness.ingestion.ingest(
            [unit_of(case) for case in cases[start : start + 50]]
        )
    outcomes = await harness.runner.process_available(limit=500)

    assert len(units) == len(cases)
    assert await harness.count(RawMessage) == len(distinct_messages) == 148
    assert await harness.count(ProcessingRun) == len(distinct_units) == 123
    statuses = [outcome.status for outcome in outcomes]
    assert len(statuses) == 123
    assert statuses.count(ProcessingStatus.NEEDS_REVIEW) == len(abstaining_units) == 8
    assert statuses.count(ProcessingStatus.SUCCEEDED) == 115
    assert await harness.count(Memory) == expected_memories == 116
    # One person can be named in several notes and is still one entity.
    entities = await harness.rows(Entity)
    assert len({(entity.entity_type, entity.normalized_name) for entity in entities}) == len(
        entities
    )

    # Same version again: nothing is created, nothing is executed.
    counts = await _counts(harness)
    again = await harness.ingestion.ingest([unit_of(case) for case in cases[:100]])
    assert all(not unit.run.created for unit in again)
    replayed = await harness.replay.replay(limit=500)
    assert len(replayed) == 123
    assert {outcome.action for outcome in replayed} == {ReplayAction.UNCHANGED}
    assert await harness.runner.process_available(limit=500) == []
    assert await _counts(harness) == counts
    assert len(extractor.requests) == 123

    # A new extractor version reprocesses every unit and keeps what the old one produced.
    old_memories = {memory.id: memory.updated_at for memory in await harness.rows(Memory)}
    next_extractor = GoldenFixtureExtractor(cases)
    next_harness = make_harness(
        next_extractor,
        timezone_name=TIMEZONE_NAME,
        descriptor=ExtractorDescriptor(provider="golden-fixture", model=None, prompt_version="2"),
    )
    created = await next_harness.replay.replay(limit=500)
    assert {outcome.action for outcome in created} == {ReplayAction.CREATED}
    assert len(await next_harness.runner.process_available(limit=500)) == 123

    assert await harness.count(RawMessage) == 148
    assert await harness.count(ProcessingRun) == 246
    memories_after = {memory.id: memory.updated_at for memory in await harness.rows(Memory)}
    assert len(memories_after) == 232
    assert {key: memories_after[key] for key in old_memories} == old_memories
