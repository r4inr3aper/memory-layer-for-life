"""Ingestion: evidence is stored once, never overwritten, and always gets a run."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.domain.enums import MessageSource, ProcessingStatus
from app.domain.errors import InvalidProcessingUnitError, SourceContentConflictError
from app.domain.identity import processing_idempotency_key
from app.models.processing_run import ProcessingRun
from app.models.processing_run_message import ProcessingRunMessage
from app.models.raw_message import RawMessage
from app.schemas.raw_message import RawMessageCreate
from tests.integration.conftest import HarnessFactory
from tests.support.extraction import ScriptedExtractor
from tests.support.pipeline import FakeClock


def _message(content: str, source_id: str | None = None) -> RawMessageCreate:
    return RawMessageCreate(
        source=MessageSource.WHATSAPP_IMPORT, content=content, source_message_id=source_id
    )


async def test_a_unit_is_stored_with_a_queued_run(
    make_harness: HarnessFactory, clock: FakeClock
) -> None:
    harness = make_harness(ScriptedExtractor())
    india = timezone(timedelta(hours=5, minutes=30))

    unit = await harness.ingest(
        "500 petrol",
        source_ids=["evt-1"],
        source=MessageSource.WHATSAPP_IMPORT,
        sent_at=datetime(2026, 3, 14, 12, 53, tzinfo=india),
    )

    (message,) = await harness.rows(RawMessage)
    assert unit.messages[0].id == message.id
    assert unit.messages[0].created is True
    assert message.source == MessageSource.WHATSAPP_IMPORT
    assert message.source_message_id == "evt-1"
    assert message.content == "500 petrol"
    assert message.content_sha256 == hashlib.sha256(b"500 petrol").hexdigest()
    assert message.ingested_at == clock()
    # Stored in UTC, whatever offset the source used.
    assert message.source_created_at == datetime(2026, 3, 14, 7, 23, tzinfo=UTC)

    (run,) = await harness.rows(ProcessingRun)
    assert unit.run.id == run.id
    assert unit.run.created is True
    assert unit.run.status is ProcessingStatus.QUEUED
    assert run.raw_message_id == message.id
    assert run.attempt_number == 1
    assert run.available_at == clock()
    assert run.pipeline_version == harness.fingerprint.pipeline_version
    assert run.metadata_["pipeline"] == harness.fingerprint.as_dict()
    assert run.idempotency_key == processing_idempotency_key([message.id], harness.fingerprint)
    assert await harness.event_types(run.id) == ["queued"]


async def test_unit_order_is_preserved(make_harness: HarnessFactory) -> None:
    harness = make_harness(ScriptedExtractor())

    unit = await harness.ingest("first", "second", "third")

    links = sorted(await harness.rows(ProcessingRunMessage), key=lambda link: link.position)
    assert [link.raw_message_id for link in links] == [message.id for message in unit.messages]
    assert [link.position for link in links] == [0, 1, 2]
    (run,) = await harness.rows(ProcessingRun)
    assert run.raw_message_id == unit.messages[0].id


async def test_redelivering_a_message_creates_nothing_new(make_harness: HarnessFactory) -> None:
    harness = make_harness(ScriptedExtractor())

    first = await harness.ingest("buy almonds", source_ids=["evt-7"])
    second = await harness.ingest("buy almonds", source_ids=["evt-7"])

    assert second.messages[0].id == first.messages[0].id
    assert second.messages[0].created is False
    assert second.run.id == first.run.id
    assert second.run.created is False
    assert await harness.count(RawMessage) == 1
    assert await harness.count(ProcessingRun) == 1
    assert await harness.event_types(first.run.id) == ["queued"]


async def test_a_source_id_redelivered_with_new_content_is_refused(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(ScriptedExtractor())
    await harness.ingest("buy almonds", source_ids=["evt-7"])

    with pytest.raises(SourceContentConflictError):
        await harness.ingest("buy cashews", source_ids=["evt-7"])

    (message,) = await harness.rows(RawMessage)
    assert message.content == "buy almonds"
    assert await harness.count(ProcessingRun) == 1


async def test_identical_text_without_a_source_id_is_two_messages(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(ScriptedExtractor())

    first = await harness.ingest("110 tom")
    second = await harness.ingest("110 tom")

    assert first.messages[0].id != second.messages[0].id
    assert first.run.id != second.run.id
    assert await harness.count(RawMessage) == 2
    assert await harness.count(ProcessingRun) == 2


async def test_the_same_message_in_another_grouping_is_another_unit(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(ScriptedExtractor())

    alone = await harness.ingest("250", source_ids=["evt-1"])
    paired = await harness.ingest("250", "Jeera", source_ids=["evt-1", "evt-2"])

    assert paired.messages[0].id == alone.messages[0].id
    assert paired.messages[0].created is False
    assert paired.messages[1].created is True
    assert paired.run.id != alone.run.id
    assert paired.run.created is True
    assert await harness.count(RawMessage) == 2
    assert await harness.count(ProcessingRun) == 2


async def test_a_unit_cannot_contain_the_same_message_twice(make_harness: HarnessFactory) -> None:
    harness = make_harness(ScriptedExtractor())

    with pytest.raises(InvalidProcessingUnitError):
        await harness.ingest("buy almonds", "buy almonds", source_ids=["evt-7", "evt-7"])

    # The whole unit was rolled back, including the first message.
    assert await harness.count(RawMessage) == 0
    assert await harness.count(ProcessingRun) == 0


async def test_a_batch_is_stored_completely_or_not_at_all(make_harness: HarnessFactory) -> None:
    harness = make_harness(ScriptedExtractor())
    await harness.ingestion.ingest([[_message("buy almonds", "evt-7")]])

    with pytest.raises(SourceContentConflictError):
        await harness.ingestion.ingest(
            [
                [_message("print photos", "evt-8")],
                [_message("buy cashews", "evt-7")],
            ]
        )

    assert await harness.count(RawMessage) == 1
    assert await harness.count(ProcessingRun) == 1


async def test_a_batch_returns_one_result_per_unit_in_order(make_harness: HarnessFactory) -> None:
    harness = make_harness(ScriptedExtractor())

    units = await harness.ingestion.ingest(
        [[_message("one", "evt-1")], [_message("two", "evt-2"), _message("three", "evt-3")]]
    )

    assert [len(unit.messages) for unit in units] == [1, 2]
    assert len({unit.run.id for unit in units}) == 2
    assert await harness.count(RawMessage) == 3


@pytest.mark.parametrize(
    "units",
    [
        pytest.param([], id="no units"),
        pytest.param([[]], id="empty unit"),
        pytest.param([[_message("x")] * 21], id="too many messages in a unit"),
        pytest.param([[_message("x")]] * 101, id="too many units"),
        pytest.param([[_message("x" * 20001)]], id="message too long"),
    ],
)
async def test_limits_are_enforced_before_anything_is_stored(
    make_harness: HarnessFactory, units: list[list[RawMessageCreate]]
) -> None:
    harness = make_harness(ScriptedExtractor())

    with pytest.raises(InvalidProcessingUnitError):
        await harness.ingestion.ingest(units)

    assert await harness.count(RawMessage) == 0


async def test_concurrent_deliveries_of_one_message_store_it_once(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(ScriptedExtractor())

    units = await asyncio.gather(
        *(harness.ingest("buy almonds", source_ids=["evt-7"]) for _ in range(8))
    )

    assert len({unit.messages[0].id for unit in units}) == 1
    assert len({unit.run.id for unit in units}) == 1
    assert sum(unit.messages[0].created for unit in units) == 1
    assert sum(unit.run.created for unit in units) == 1
    assert await harness.count(RawMessage) == 1
    assert await harness.count(ProcessingRun) == 1
    assert await harness.event_types(units[0].run.id) == ["queued"]


async def test_the_same_id_from_another_source_is_another_message(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(ScriptedExtractor())

    await harness.ingest("buy almonds", source_ids=["7"], source=MessageSource.WHATSAPP_IMPORT)
    await harness.ingest("buy cashews", source_ids=["7"], source=MessageSource.MANUAL_CAPTURE)

    assert await harness.count(RawMessage) == 2
