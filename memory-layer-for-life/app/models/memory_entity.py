import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.constraints import enum_check
from app.domain.enums import MemoryEntityRelation

if TYPE_CHECKING:
    from app.models.entity import Entity
    from app.models.memory import Memory


class MemoryEntity(Base, TimestampMixin):
    """Link between a memory and a canonical entity it involves."""

    __tablename__ = "memory_entities"

    memory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="RESTRICT"), primary_key=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="RESTRICT"), primary_key=True
    )
    relationship_type: Mapped[str] = mapped_column(String(50), primary_key=True)

    __table_args__ = (
        CheckConstraint(
            enum_check("relationship_type", MemoryEntityRelation), name="valid_relationship_type"
        ),
        Index("ix_memory_entities_entity_id", "entity_id"),
    )

    memory: Mapped["Memory"] = relationship("Memory", back_populates="memory_entities")
    entity: Mapped["Entity"] = relationship("Entity", back_populates="memory_entities")
