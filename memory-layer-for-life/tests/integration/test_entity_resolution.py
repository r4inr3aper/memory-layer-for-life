"""Entity resolution through the pipeline: conservative, auditable, and race-free."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import utc_now
from app.db.base import new_uuid
from app.domain.enums import (
    EntityStatus,
    EntityType,
    MemoryEntityRelation,
    MentionResolutionStatus,
    ProcessingStatus,
)
from app.integrations.extraction.base import ExtractionRequest, ExtractionResponse
from app.models.entity import Entity
from app.models.entity_mention import EntityMention
from app.models.memory_entity import MemoryEntity
from tests.integration.conftest import HarnessFactory
from tests.support.extraction import ScriptedExtractor, extraction, memory, mention


def _mentioning(name: str, entity_type: EntityType = EntityType.PERSON, **kwargs: object):  # type: ignore[no-untyped-def]
    return extraction(
        memory(f"Something about {name}", mention_indexes=[0]),
        mentions=[mention(name, entity_type=entity_type, **kwargs)],  # type: ignore[arg-type]
    )


async def _add_entity(
    session_factory: async_sessionmaker[AsyncSession],
    name: str,
    *,
    entity_type: EntityType = EntityType.PERSON,
    status: EntityStatus = EntityStatus.ACTIVE,
    merged_into: Entity | None = None,
) -> Entity:
    now = utc_now()
    entity = Entity(
        id=new_uuid(),
        entity_type=entity_type.value,
        canonical_name=name,
        normalized_name=name.casefold(),
        status=status.value,
        merged_into_id=merged_into.id if merged_into is not None else None,
        attributes={},
        created_at=now,
        updated_at=now,
    )
    async with session_factory() as session, session.begin():
        session.add(entity)
    return entity


async def test_a_new_name_creates_an_entity_and_resolves_to_it(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(ScriptedExtractor(_mentioning("Asha")))

    await harness.ingest_and_process("call Asha tomorrow")

    (entity,) = await harness.rows(Entity)
    assert entity.canonical_name == "Asha"
    assert entity.normalized_name == "asha"
    assert entity.entity_type == EntityType.PERSON
    assert entity.status == EntityStatus.ACTIVE

    (stored,) = await harness.rows(EntityMention)
    assert stored.mention_text == "Asha"
    assert stored.normalized_mention == "asha"
    assert stored.ordinal == 0
    assert stored.resolution_status == MentionResolutionStatus.RESOLVED
    assert stored.resolved_entity_id == entity.id
    # Offsets are located in the stored message, never taken from the model.
    assert (stored.start_offset, stored.end_offset) == (5, 9)

    (link,) = await harness.rows(MemoryEntity)
    assert link.entity_id == entity.id
    assert link.relationship_type == MemoryEntityRelation.MENTIONS


async def test_a_known_name_reuses_the_entity(make_harness: HarnessFactory) -> None:
    harness = make_harness(ScriptedExtractor(_mentioning("Asha"), _mentioning("asha.")))

    await harness.ingest_and_process("call Asha")
    await harness.ingest_and_process("lunch with asha.")

    (entity,) = await harness.rows(Entity)
    mentions = await harness.rows(EntityMention)
    assert len(mentions) == 2
    assert {item.resolved_entity_id for item in mentions} == {entity.id}
    # The first spelling stays the canonical name.
    assert entity.canonical_name == "Asha"


async def test_the_same_name_with_another_type_is_another_entity(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(
        ScriptedExtractor(
            _mentioning("Mercury", EntityType.PROJECT), _mentioning("Mercury", EntityType.TOPIC)
        )
    )

    await harness.ingest_and_process("Mercury launch plan")
    await harness.ingest_and_process("read about Mercury")

    entities = await harness.rows(Entity)
    assert sorted(entity.entity_type for entity in entities) == ["project", "topic"]


async def test_two_candidates_leave_the_mention_ambiguous(
    make_harness: HarnessFactory, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _add_entity(session_factory, "Rahul")
    await _add_entity(session_factory, "Rahul")
    harness = make_harness(ScriptedExtractor(_mentioning("Rahul")))

    _, outcome = await harness.ingest_and_process("ask Rahul about the invoice")

    # Ambiguity is recorded, not guessed away, and the run still succeeds.
    assert outcome.status is ProcessingStatus.SUCCEEDED
    (stored,) = await harness.rows(EntityMention)
    assert stored.resolution_status == MentionResolutionStatus.AMBIGUOUS
    assert stored.resolved_entity_id is None
    assert await harness.count(Entity) == 2
    assert await harness.count(MemoryEntity) == 0


async def test_a_merged_entity_resolves_to_the_entity_it_was_merged_into(
    make_harness: HarnessFactory, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    survivor = await _add_entity(session_factory, "Robert")
    await _add_entity(session_factory, "Bob", status=EntityStatus.MERGED, merged_into=survivor)
    harness = make_harness(ScriptedExtractor(_mentioning("Bob")))

    await harness.ingest_and_process("Bob owes me a coffee")

    (stored,) = await harness.rows(EntityMention)
    assert stored.resolution_status == MentionResolutionStatus.RESOLVED
    assert stored.resolved_entity_id == survivor.id
    assert await harness.count(Entity) == 2


async def test_an_archived_entity_is_not_a_candidate(
    make_harness: HarnessFactory, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    archived = await _add_entity(
        session_factory, "Acme", entity_type=EntityType.ORGANIZATION, status=EntityStatus.ARCHIVED
    )
    harness = make_harness(ScriptedExtractor(_mentioning("Acme", EntityType.ORGANIZATION)))

    await harness.ingest_and_process("Acme renewed the contract")

    (stored,) = await harness.rows(EntityMention)
    assert stored.resolution_status == MentionResolutionStatus.RESOLVED
    assert stored.resolved_entity_id != archived.id
    assert await harness.count(Entity) == 2


async def test_text_that_cannot_be_a_name_stays_unresolved(make_harness: HarnessFactory) -> None:
    harness = make_harness(ScriptedExtractor(_mentioning("...")))

    _, outcome = await harness.ingest_and_process("... said hello")

    assert outcome.status is ProcessingStatus.SUCCEEDED
    (stored,) = await harness.rows(EntityMention)
    assert stored.resolution_status == MentionResolutionStatus.UNRESOLVED
    assert stored.resolved_entity_id is None
    assert await harness.count(Entity) == 0


async def test_a_mention_that_is_not_in_the_message_has_no_offsets(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(ScriptedExtractor(_mentioning("Bengaluru", EntityType.PLACE)))

    await harness.ingest_and_process("hackathons in blr")

    (stored,) = await harness.rows(EntityMention)
    assert (stored.start_offset, stored.end_offset) == (None, None)
    assert stored.mention_text == "Bengaluru"


async def test_the_same_name_in_two_messages_of_a_unit_gives_two_mentions(
    make_harness: HarnessFactory,
) -> None:
    output = extraction(
        memory("Two notes mention Tom and 110", mention_indexes=[0, 1]),
        mentions=[mention("tom", message_index=0), mention("tom", message_index=1)],
    )
    harness = make_harness(ScriptedExtractor(output))

    unit, outcome = await harness.ingest_and_process("110 tom", "110 tom")

    assert outcome.status is ProcessingStatus.SUCCEEDED
    mentions = sorted(await harness.rows(EntityMention), key=lambda item: item.ordinal)
    assert [item.raw_message_id for item in mentions] == [message.id for message in unit.messages]
    assert [(item.start_offset, item.end_offset) for item in mentions] == [(4, 7), (4, 7)]
    assert await harness.count(Entity) == 1
    # Both mentions resolve to one entity, so the memory is linked to it once.
    assert await harness.count(MemoryEntity) == 1


async def test_concurrent_runs_create_a_new_entity_only_once(make_harness: HarnessFactory) -> None:
    """Two runs meet the same unknown name at the same time."""
    both_extracting = asyncio.Barrier(2)

    class SynchronizedExtractor(ScriptedExtractor):
        async def extract(self, request: ExtractionRequest) -> ExtractionResponse:
            # Release both runs into entity resolution together.
            await both_extracting.wait()
            return await super().extract(request)

    harness = make_harness(SynchronizedExtractor(_mentioning("Zed")))
    first = await harness.ingest("Zed joined the team")
    second = await harness.ingest("pair with Zed on Friday")

    outcomes = await asyncio.gather(
        harness.runner.process_run(first.run.id), harness.runner.process_run(second.run.id)
    )

    assert [outcome.status for outcome in outcomes] == [ProcessingStatus.SUCCEEDED] * 2
    (entity,) = await harness.rows(Entity)
    mentions = await harness.rows(EntityMention)
    assert len(mentions) == 2
    assert {item.resolved_entity_id for item in mentions} == {entity.id}
