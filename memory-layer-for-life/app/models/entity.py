import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import EntityStatus, EntityType

if TYPE_CHECKING:
    from app.models.entity_mention import EntityMention
    from app.models.memory_entity import MemoryEntity


class Entity(Base, UUIDMixin, UpdateTimestampMixin):
    """Canonical person, organization, project, technology, place, and so on.

    ``normalized_name`` is deliberately not unique: two different people can share a
    name. Identity is decided by entity resolution, not by spelling.
    """

    __tablename__ = "entities"

    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=EntityStatus.ACTIVE.value,
        server_default=EntityStatus.ACTIVE.value,
    )
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="RESTRICT"), nullable=True
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # The app user whose chats this came from. Empty for the operator's own memory store
    # (the console and imports). Everything derived from a message has its owner.
    # Resolution only ever matches entities of the same owner.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("merged_into_id != id", name="no_self_merge"),
        CheckConstraint(enum_check("entity_type", EntityType), name="valid_entity_type"),
        CheckConstraint(enum_check("status", EntityStatus), name="valid_entity_status"),
        CheckConstraint(
            "(status = 'merged') = (merged_into_id IS NOT NULL)", name="merged_has_target"
        ),
        CheckConstraint("length(normalized_name) > 0", name="non_empty_normalized_name"),
        Index("ix_entities_type_normalized_name", "entity_type", "normalized_name"),
        Index("ix_entities_entity_type", "entity_type"),
        Index("ix_entities_owner_id", "owner_id"),
        # Trigram index, so a name written slightly differently in a question still finds
        # the entity (pg_trgm).
        Index(
            "ix_entities_normalized_name_trgm",
            "normalized_name",
            postgresql_using="gin",
            postgresql_ops={"normalized_name": "gin_trgm_ops"},
        ),
    )

    merged_into: Mapped["Entity | None"] = relationship("Entity", remote_side="Entity.id")
    mentions: Mapped[list["EntityMention"]] = relationship(
        "EntityMention", back_populates="resolved_entity"
    )
    memory_entities: Mapped[list["MemoryEntity"]] = relationship(
        "MemoryEntity", back_populates="entity"
    )
