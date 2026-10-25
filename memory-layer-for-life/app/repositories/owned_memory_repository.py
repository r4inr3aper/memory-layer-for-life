import uuid

from sqlalchemy import delete, or_, select, update

from app.domain.enums import EntityStatus
from app.models.entity import Entity
from app.models.entity_mention import EntityMention
from app.models.extraction_result import ExtractionResult
from app.models.llm_call import LlmCall
from app.models.memory import Memory
from app.models.memory_entity import MemoryEntity
from app.models.memory_relation import MemoryRelation
from app.models.memory_source import MemorySource
from app.models.processing_run import ProcessingRun
from app.models.processing_run_event import ProcessingRunEvent
from app.models.processing_run_message import ProcessingRunMessage
from app.models.raw_message import RawMessage
from app.repositories.base import BaseRepository


class OwnedMemoryRepository(BaseRepository):
    """Deletes everything the memory pipeline holds for one app user, for account deletion.

    Evidence is otherwise never deleted, and every derived record restricts deleting what
    it points at, so this goes in dependency order: memory links and provenance, the
    memories, entity mentions and entities, the pipeline's records with their call log,
    and the evidence last. Rows are selected by stable predicates (the owner, and runs by
    their first message), never by lists of ids, so a long history stays one statement each.
    A unit never mixes owners, so nothing here touches anyone else's data.
    """

    async def delete_for(self, owner_id: uuid.UUID) -> None:
        memories = select(Memory.id).where(Memory.owner_id == owner_id)
        messages = select(RawMessage.id).where(RawMessage.owner_id == owner_id)
        runs = select(ProcessingRun.id).where(ProcessingRun.raw_message_id.in_(messages))

        await self._session.execute(
            delete(MemoryRelation).where(
                or_(
                    MemoryRelation.source_memory_id.in_(memories),
                    MemoryRelation.target_memory_id.in_(memories),
                )
            )
        )
        await self._session.execute(
            delete(MemoryEntity).where(MemoryEntity.memory_id.in_(memories))
        )
        await self._session.execute(
            delete(MemorySource).where(MemorySource.memory_id.in_(memories))
        )
        # Memories can supersede each other; unlink them so each can go.
        await self._session.execute(
            update(Memory).where(Memory.owner_id == owner_id).values(supersedes_memory_id=None)
        )
        await self._session.execute(delete(Memory).where(Memory.owner_id == owner_id))

        await self._session.execute(
            delete(EntityMention).where(EntityMention.raw_message_id.in_(messages))
        )
        # A merged entity points at the one it was merged into; archive it to unlink it.
        await self._session.execute(
            update(Entity)
            .where(Entity.owner_id == owner_id, Entity.merged_into_id.is_not(None))
            .values(status=EntityStatus.ARCHIVED.value, merged_into_id=None)
        )
        await self._session.execute(delete(Entity).where(Entity.owner_id == owner_id))

        await self._session.execute(delete(LlmCall).where(LlmCall.processing_run_id.in_(runs)))
        await self._session.execute(
            delete(ProcessingRunEvent).where(ProcessingRunEvent.processing_run_id.in_(runs))
        )
        await self._session.execute(
            delete(ExtractionResult).where(ExtractionResult.processing_run_id.in_(runs))
        )
        await self._session.execute(
            delete(ProcessingRunMessage).where(ProcessingRunMessage.processing_run_id.in_(runs))
        )
        await self._session.execute(delete(ProcessingRun).where(ProcessingRun.id.in_(runs)))
        await self._session.execute(delete(RawMessage).where(RawMessage.owner_id == owner_id))
