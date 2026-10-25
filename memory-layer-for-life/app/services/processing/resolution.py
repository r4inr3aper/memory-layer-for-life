"""Entity resolution: decide which canonical entity a mention refers to.

The policy is deliberately conservative and fully deterministic:

* A mention matches an entity only when type and normalized name are equal. There is no
  fuzzy matching: similar names do not prove identity.
* Exactly one active candidate resolves the mention. Merged entities count through the
  entity they were merged into.
* Several candidates leave the mention ``ambiguous``. Nothing is guessed and no link is
  written, so a later correction has nothing to undo.
* No candidate creates a new entity, because a name seen for the first time has to start
  somewhere. Text that cannot serve as a name stays ``unresolved``.

Every decision is stored on the mention together with the original text, so resolution
can be audited and redone.
"""

import uuid
from dataclasses import dataclass

from app.core.clock import Clock
from app.db.base import new_uuid
from app.domain.enums import EntityStatus, EntityType, MentionResolutionStatus
from app.domain.normalization import normalize_entity_name
from app.models.entity import Entity
from app.repositories.entity_repository import EntityRepository

# Column limit of ``entities.normalized_name`` and ``entities.canonical_name``.
_MAX_ENTITY_NAME_LENGTH = 500


@dataclass(frozen=True, slots=True)
class MentionResolution:
    normalized_mention: str
    status: MentionResolutionStatus
    entity_id: uuid.UUID | None = None


def is_usable_name(normalized_name: str) -> bool:
    """Whether normalized text can identify an entity at all."""
    return 0 < len(normalized_name) <= _MAX_ENTITY_NAME_LENGTH and any(
        character.isalnum() for character in normalized_name
    )


class EntityResolver:
    """Resolves the mentions of one owner's messages: candidates and new entities are
    that owner's only, so two people's "Mom" never become one entity."""

    def __init__(
        self, entities: EntityRepository, *, owner_id: uuid.UUID | None, clock: Clock
    ) -> None:
        self._entities = entities
        self._owner_id = owner_id
        self._clock = clock

    async def resolve(self, entity_type: EntityType, mention_text: str) -> MentionResolution:
        normalized = normalize_entity_name(mention_text)
        if not is_usable_name(normalized):
            return MentionResolution(normalized, MentionResolutionStatus.UNRESOLVED)

        # Held until the surrounding transaction ends, so two runs that meet the same new
        # name cannot both create an entity for it.
        await self._entities.lock_name(self._owner_id, entity_type.value, normalized)
        candidates = await self._entities.find_active_targets(
            self._owner_id, entity_type.value, normalized
        )

        if len(candidates) > 1:
            return MentionResolution(normalized, MentionResolutionStatus.AMBIGUOUS)
        if len(candidates) == 1:
            return MentionResolution(normalized, MentionResolutionStatus.RESOLVED, candidates[0])

        now = self._clock()
        entity = await self._entities.add(
            Entity(
                id=new_uuid(),
                entity_type=entity_type.value,
                canonical_name=mention_text.strip()[:_MAX_ENTITY_NAME_LENGTH],
                normalized_name=normalized,
                status=EntityStatus.ACTIVE.value,
                attributes={},
                owner_id=self._owner_id,
                created_at=now,
                updated_at=now,
            )
        )
        return MentionResolution(normalized, MentionResolutionStatus.RESOLVED, entity.id)
