import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import RelationType

if TYPE_CHECKING:
    from app.models.memory import Memory


class MemoryRelation(Base, UUIDMixin, TimestampMixin):
    """Typed, directed relationship between two memories."""

    __tablename__ = "memory_relations"

    source_memory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="RESTRICT"), nullable=False
    )
    target_memory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="RESTRICT"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2, asdecimal=False), nullable=True)

    __table_args__ = (
        CheckConstraint("source_memory_id != target_memory_id", name="no_self_relation"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="valid_relation_confidence",
        ),
        CheckConstraint(enum_check("relation_type", RelationType), name="valid_relation_type"),
        UniqueConstraint(
            "source_memory_id",
            "target_memory_id",
            "relation_type",
            name="uq_memory_relations_source_target_type",
        ),
        Index("ix_memory_relations_source_memory_id", "source_memory_id"),
        Index("ix_memory_relations_target_memory_id", "target_memory_id"),
    )

    source_memory: Mapped["Memory"] = relationship(
        "Memory", foreign_keys=[source_memory_id], back_populates="outgoing_relations"
    )
    target_memory: Mapped["Memory"] = relationship(
        "Memory", foreign_keys=[target_memory_id], back_populates="incoming_relations"
    )
