import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.domain.enums import EntityStatus
from app.models.entity import Entity
from app.models.entity_mention import EntityMention
from app.repositories.base import BaseRepository


class EntityRepository(BaseRepository):
    """Persistence of canonical entities and of the mentions that point at them."""

    async def lock_name(
        self, owner_id: uuid.UUID | None, entity_type: str, normalized_name: str
    ) -> None:
        """Serialize find-or-create for one name until the transaction ends.

        Entity names are deliberately not unique, so no constraint can stop two concurrent
        runs from both creating "the first" entity for a new name. A transaction-scoped
        advisory lock on the name closes that race without forbidding namesakes.
        """
        owner = owner_id or "operator"
        lock_key = func.hashtextextended(f"entity:{owner}:{entity_type}:{normalized_name}", 0)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    async def find_active_targets(
        self, owner_id: uuid.UUID | None, entity_type: str, normalized_name: str
    ) -> list[uuid.UUID]:
        """Active entities a name can refer to, among the owner's entities only.

        Starts from active and merged entities with this type and normalized name, follows
        ``merged_into_id`` to the surviving entity, and returns the distinct active ones.
        Archived entities are never candidates.
        """
        chain = (
            select(Entity.id, Entity.status, Entity.merged_into_id)
            .where(
                Entity.owner_id.is_(None) if owner_id is None else Entity.owner_id == owner_id,
                Entity.entity_type == entity_type,
                Entity.normalized_name == normalized_name,
                Entity.status.in_([EntityStatus.ACTIVE.value, EntityStatus.MERGED.value]),
            )
            .cte("resolution_chain", recursive=True)
        )
        merge_target = aliased(Entity)
        # UNION (not UNION ALL) drops repeated rows, which also ends a cyclic merge chain.
        chain = chain.union(
            select(merge_target.id, merge_target.status, merge_target.merged_into_id).where(
                merge_target.id == chain.c.merged_into_id
            )
        )
        rows = await self._session.scalars(
            select(chain.c.id)
            .where(chain.c.status == EntityStatus.ACTIVE.value)
            .order_by(chain.c.id)
        )
        return list(rows)

    async def add(self, entity: Entity) -> Entity:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def add_mentions(self, mentions: Sequence[EntityMention]) -> None:
        self._session.add_all(mentions)
        await self._session.flush()
