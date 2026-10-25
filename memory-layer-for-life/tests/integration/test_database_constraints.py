"""Database constraints: the last line of defense behind application validation.

Each test writes one row that breaks exactly one rule and expects PostgreSQL to refuse it.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import new_uuid
from app.domain.enums import (
    EntityStatus,
    EntityType,
    ExtractionStatus,
    MemoryEntityRelation,
    MemoryType,
    MentionResolutionStatus,
    MessageSource,
    ProcessingStatus,
    RelationType,
    RunEventType,
    SourceRole,
)
from app.models.entity import Entity
from app.models.entity_mention import EntityMention
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from app.models.memory_entity import MemoryEntity
from app.models.memory_relation import MemoryRelation
from app.models.memory_source import MemorySource
from app.models.processing_run import ProcessingRun
from app.models.processing_run_event import ProcessingRunEvent
from app.models.processing_run_message import ProcessingRunMessage
from app.models.raw_message import RawMessage

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def raw_message(content: str = "Test message", **overrides: Any) -> RawMessage:
    values: dict[str, Any] = {
        "source": MessageSource.API_INPUT.value,
        "content": content,
        "content_sha256": _sha(content),
    }
    values.update(overrides)
    return RawMessage(**values)


def processing_run(message: RawMessage, key: str = "key-1", **overrides: Any) -> ProcessingRun:
    values: dict[str, Any] = {
        "raw_message_id": message.id,
        "pipeline_version": "1.0.0",
        "idempotency_key": key,
    }
    values.update(overrides)
    return ProcessingRun(**values)


def extraction_result(run: ProcessingRun, **overrides: Any) -> ExtractionResult:
    values: dict[str, Any] = {
        "processing_run_id": run.id,
        "schema_version": "1.0",
        "extractor_version": "scripted:1",
        "status": ExtractionStatus.SUCCEEDED.value,
    }
    values.update(overrides)
    return ExtractionResult(**values)


def entity(name: str = "John Doe", **overrides: Any) -> Entity:
    values: dict[str, Any] = {
        "entity_type": EntityType.PERSON.value,
        "canonical_name": name,
        "normalized_name": name.casefold(),
    }
    values.update(overrides)
    return Entity(**values)


def memory_row(content: str = "A fact", **overrides: Any) -> Memory:
    values: dict[str, Any] = {"memory_type": MemoryType.SEMANTIC_FACT.value, "content": content}
    values.update(overrides)
    return Memory(**values)


async def persist(session: AsyncSession, *rows: Any) -> None:
    session.add_all(rows)
    await session.flush()


async def assert_rejected(session: AsyncSession, *rows: Any) -> None:
    """The rows must violate a constraint when written."""
    session.add_all(rows)
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def _chain(session: AsyncSession) -> tuple[RawMessage, ProcessingRun, ExtractionResult]:
    """A stored message, run, and extraction result to hang other rows on."""
    message = raw_message(id=new_uuid())
    run = processing_run(message, id=new_uuid())
    result = extraction_result(run, id=new_uuid())
    await persist(session, message)
    await persist(session, run)
    await persist(session, result)
    return message, run, result


# --- raw_messages ---------------------------------------------------------------------


async def test_database_connection(db_session: AsyncSession) -> None:
    assert (await db_session.execute(text("SELECT 1"))).scalar() == 1


async def test_raw_message_defaults_are_applied(db_session: AsyncSession) -> None:
    message = raw_message()
    await persist(db_session, message)

    assert isinstance(message.id, uuid.UUID)
    assert message.id.version == 7
    assert message.created_at.tzinfo is not None
    assert message.metadata_ == {}


async def test_source_identity_is_unique(db_session: AsyncSession) -> None:
    await persist(db_session, raw_message("A", source_message_id="123"))
    await db_session.commit()

    await assert_rejected(db_session, raw_message("B", source_message_id="123"))


async def test_messages_without_a_source_id_may_repeat(db_session: AsyncSession) -> None:
    await persist(db_session, raw_message("same text"), raw_message("same text"))


async def test_content_hash_must_be_a_sha256(db_session: AsyncSession) -> None:
    await assert_rejected(db_session, raw_message(content_sha256="fakehash"))


async def test_content_must_not_be_empty(db_session: AsyncSession) -> None:
    await assert_rejected(db_session, raw_message("", content_sha256=_sha("")))


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"content": "rewritten"}, id="content"),
        pytest.param({"content_sha256": _sha("rewritten")}, id="hash"),
        pytest.param({"source_message_id": "other"}, id="source id"),
        pytest.param({"metadata_": {"edited": True}}, id="metadata"),
    ],
)
async def test_raw_messages_cannot_be_updated(
    db_session: AsyncSession, changes: dict[str, Any]
) -> None:
    message = raw_message("original")
    await persist(db_session, message)
    await db_session.commit()
    message_id = message.id

    with pytest.raises(IntegrityError, match="immutable"):
        await db_session.execute(
            update(RawMessage).where(RawMessage.id == message_id).values(**changes)
        )
    await db_session.rollback()

    stored = await db_session.get(RawMessage, message_id, populate_existing=True)
    assert stored is not None
    assert stored.content == "original"


async def test_a_message_with_a_run_cannot_be_deleted(db_session: AsyncSession) -> None:
    message, _, _ = await _chain(db_session)
    await db_session.commit()

    await db_session.delete(message)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# --- processing_runs ------------------------------------------------------------------


async def test_run_defaults_are_applied(db_session: AsyncSession) -> None:
    message = raw_message(id=new_uuid())
    await persist(db_session, message)
    run = processing_run(message)
    await persist(db_session, run)

    assert run.status == ProcessingStatus.QUEUED
    assert run.attempt_number == 1
    assert run.available_at is not None


async def test_idempotency_key_is_unique(db_session: AsyncSession) -> None:
    message = raw_message(id=new_uuid())
    await persist(db_session, message)
    await persist(db_session, processing_run(message, "same-key"))
    await db_session.commit()

    await assert_rejected(db_session, processing_run(message, "same-key"))


async def test_attempt_number_must_be_positive(db_session: AsyncSession) -> None:
    message = raw_message(id=new_uuid())
    await persist(db_session, message)
    await db_session.commit()

    await assert_rejected(db_session, processing_run(message, attempt_number=0))


async def test_run_status_is_controlled(db_session: AsyncSession) -> None:
    message = raw_message(id=new_uuid())
    await persist(db_session, message)
    await db_session.commit()

    await assert_rejected(db_session, processing_run(message, status="exploded"))


async def test_a_unit_position_is_used_once_per_run(db_session: AsyncSession) -> None:
    message, run, _ = await _chain(db_session)
    other = raw_message("other", id=new_uuid())
    await persist(db_session, other)
    await persist(
        db_session,
        ProcessingRunMessage(processing_run_id=run.id, raw_message_id=message.id, position=0),
    )
    await db_session.commit()

    await assert_rejected(
        db_session,
        ProcessingRunMessage(processing_run_id=run.id, raw_message_id=other.id, position=0),
    )


async def test_a_message_appears_once_per_run(db_session: AsyncSession) -> None:
    message, run, _ = await _chain(db_session)
    await persist(
        db_session,
        ProcessingRunMessage(processing_run_id=run.id, raw_message_id=message.id, position=0),
    )
    await db_session.commit()

    await assert_rejected(
        db_session,
        ProcessingRunMessage(processing_run_id=run.id, raw_message_id=message.id, position=1),
    )


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"event_type": "celebrated"}, id="event type"),
        pytest.param({"stage": "teleport"}, id="stage"),
        pytest.param({"attempt_number": 0}, id="attempt number"),
    ],
)
async def test_run_events_are_controlled(
    db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    _, run, _ = await _chain(db_session)
    await db_session.commit()
    values: dict[str, Any] = {
        "processing_run_id": run.id,
        "attempt_number": 1,
        "event_type": RunEventType.QUEUED.value,
    }
    values.update(overrides)

    await assert_rejected(db_session, ProcessingRunEvent(**values))


# --- extraction_results ---------------------------------------------------------------


async def test_a_run_has_at_most_one_extraction_result(db_session: AsyncSession) -> None:
    _, run, _ = await _chain(db_session)
    await db_session.commit()

    await assert_rejected(db_session, extraction_result(run))


async def test_extraction_status_is_controlled(db_session: AsyncSession) -> None:
    message = raw_message(id=new_uuid())
    run = processing_run(message, id=new_uuid())
    await persist(db_session, message)
    await persist(db_session, run)
    await db_session.commit()

    await assert_rejected(db_session, extraction_result(run, status="completed"))


# --- entities and mentions ------------------------------------------------------------


async def test_entity_cannot_be_merged_into_itself(db_session: AsyncSession) -> None:
    item = entity(id=new_uuid())
    await persist(db_session, item)
    item.status = EntityStatus.MERGED.value
    item.merged_into_id = item.id

    with pytest.raises(IntegrityError, match="no_self_merge"):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"status": EntityStatus.MERGED.value}, id="merged without a target"),
        pytest.param({"entity_type": "spaceship"}, id="unknown type"),
        pytest.param({"status": "deprecated"}, id="unknown status"),
        pytest.param({"normalized_name": ""}, id="empty normalized name"),
    ],
)
async def test_entity_values_are_controlled(
    db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    await assert_rejected(db_session, entity(**overrides))


async def test_an_active_entity_cannot_point_at_a_merge_target(db_session: AsyncSession) -> None:
    target = entity("Robert", id=new_uuid())
    await persist(db_session, target)
    await db_session.commit()

    await assert_rejected(db_session, entity("Bob", merged_into_id=target.id))


def _mention(message: RawMessage, result: ExtractionResult, **overrides: Any) -> EntityMention:
    values: dict[str, Any] = {
        "raw_message_id": message.id,
        "extraction_result_id": result.id,
        "ordinal": 0,
        "entity_type": EntityType.PERSON.value,
        "mention_text": "Asha",
        "normalized_mention": "asha",
    }
    values.update(overrides)
    return EntityMention(**values)


async def test_mention_ordinal_is_unique_per_extraction_result(db_session: AsyncSession) -> None:
    message, _, result = await _chain(db_session)
    await persist(db_session, _mention(message, result))
    await db_session.commit()

    await assert_rejected(db_session, _mention(message, result, mention_text="Bina"))


async def test_the_same_text_can_be_mentioned_twice(db_session: AsyncSession) -> None:
    message, _, result = await _chain(db_session)

    await persist(
        db_session,
        _mention(message, result, ordinal=0, start_offset=0, end_offset=4),
        _mention(message, result, ordinal=1, start_offset=0, end_offset=4),
    )


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"resolution_status": MentionResolutionStatus.RESOLVED.value},
            id="resolved without an entity",
        ),
        pytest.param({"resolution_status": "guessed"}, id="unknown resolution status"),
        pytest.param({"entity_type": "spaceship"}, id="unknown entity type"),
        pytest.param({"ordinal": -1}, id="negative ordinal"),
        pytest.param({"start_offset": 3}, id="start offset without end"),
        pytest.param({"start_offset": 5, "end_offset": 2}, id="end before start"),
        pytest.param({"confidence": 1.5}, id="confidence above one"),
    ],
)
async def test_mention_values_are_controlled(
    db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    message, _, result = await _chain(db_session)
    await db_session.commit()

    await assert_rejected(db_session, _mention(message, result, **overrides))


async def test_an_unresolved_mention_cannot_point_at_an_entity(db_session: AsyncSession) -> None:
    message, _, result = await _chain(db_session)
    target = entity(id=new_uuid())
    await persist(db_session, target)
    await db_session.commit()

    await assert_rejected(db_session, _mention(message, result, resolved_entity_id=target.id))


# --- memories -------------------------------------------------------------------------


async def test_memory_defaults_are_applied(db_session: AsyncSession) -> None:
    item = memory_row()
    await persist(db_session, item)

    assert item.status == "proposed"
    assert item.metadata_ == {}
    assert item.origin_extraction_result_id is None


async def test_memory_cannot_supersede_itself(db_session: AsyncSession) -> None:
    item = memory_row(id=new_uuid())
    await persist(db_session, item)
    item.supersedes_memory_id = item.id

    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"confidence": 1.5}, id="confidence above one"),
        pytest.param({"confidence": -0.1}, id="confidence below zero"),
        pytest.param({"memory_type": "rumour"}, id="unknown type"),
        pytest.param({"status": "deleted"}, id="unknown status"),
        pytest.param({"content": ""}, id="empty content"),
        pytest.param({"origin_ordinal": 0}, id="ordinal without an origin"),
        pytest.param(
            {"valid_from": NOW, "valid_until": NOW - timedelta(days=1)},
            id="validity ends before it starts",
        ),
    ],
)
async def test_memory_values_are_controlled(
    db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    await assert_rejected(db_session, memory_row(**overrides))


async def test_an_origin_needs_an_ordinal(db_session: AsyncSession) -> None:
    _, _, result = await _chain(db_session)
    await db_session.commit()

    await assert_rejected(db_session, memory_row(origin_extraction_result_id=result.id))


async def test_one_extraction_output_cannot_become_two_memories(db_session: AsyncSession) -> None:
    _, _, result = await _chain(db_session)
    await persist(
        db_session, memory_row("First", origin_extraction_result_id=result.id, origin_ordinal=0)
    )
    await db_session.commit()

    await assert_rejected(
        db_session, memory_row("Again", origin_extraction_result_id=result.id, origin_ordinal=0)
    )


# --- provenance and relations ---------------------------------------------------------


def _source(
    item: Memory, message: RawMessage, result: ExtractionResult, **overrides: Any
) -> MemorySource:
    values: dict[str, Any] = {
        "memory_id": item.id,
        "raw_message_id": message.id,
        "extraction_result_id": result.id,
        "source_role": SourceRole.SUPPORTING.value,
    }
    values.update(overrides)
    return MemorySource(**values)


async def test_a_memory_can_rest_on_several_messages_of_one_extraction(
    db_session: AsyncSession,
) -> None:
    message, _, result = await _chain(db_session)
    second = raw_message("second", id=new_uuid())
    item = memory_row(id=new_uuid())
    await persist(db_session, second, item)

    await persist(db_session, _source(item, message, result), _source(item, second, result))


async def test_a_source_link_is_not_duplicated(db_session: AsyncSession) -> None:
    message, _, result = await _chain(db_session)
    item = memory_row(id=new_uuid())
    await persist(db_session, item)
    await persist(db_session, _source(item, message, result))
    await db_session.commit()

    await assert_rejected(db_session, _source(item, message, result))


async def test_source_role_is_controlled(db_session: AsyncSession) -> None:
    message, _, result = await _chain(db_session)
    item = memory_row(id=new_uuid())
    await persist(db_session, item)
    await db_session.commit()

    await assert_rejected(db_session, _source(item, message, result, source_role="hearsay"))


async def test_memory_entity_relationship_is_controlled(db_session: AsyncSession) -> None:
    item = memory_row(id=new_uuid())
    target = entity(id=new_uuid())
    await persist(db_session, item, target)
    await persist(
        db_session,
        MemoryEntity(
            memory_id=item.id,
            entity_id=target.id,
            relationship_type=MemoryEntityRelation.MENTIONS.value,
        ),
    )
    await db_session.commit()

    await assert_rejected(
        db_session,
        MemoryEntity(memory_id=item.id, entity_id=target.id, relationship_type="admires"),
    )


async def test_memory_relation_rules(db_session: AsyncSession) -> None:
    first_id, second_id = new_uuid(), new_uuid()
    await persist(db_session, memory_row("First", id=first_id), memory_row("Second", id=second_id))
    await persist(
        db_session,
        MemoryRelation(
            source_memory_id=first_id,
            target_memory_id=second_id,
            relation_type=RelationType.DEPENDS_ON.value,
        ),
    )
    await db_session.commit()

    await assert_rejected(  # the same directed relation twice
        db_session,
        MemoryRelation(
            source_memory_id=first_id,
            target_memory_id=second_id,
            relation_type=RelationType.DEPENDS_ON.value,
        ),
    )
    await assert_rejected(  # a memory related to itself
        db_session,
        MemoryRelation(
            source_memory_id=first_id,
            target_memory_id=first_id,
            relation_type=RelationType.SUPPORTS.value,
        ),
    )
    await assert_rejected(  # an unknown relation type
        db_session,
        MemoryRelation(
            source_memory_id=second_id, target_memory_id=first_id, relation_type="rhymes_with"
        ),
    )
