import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import SourceRole

if TYPE_CHECKING:
    from app.models.extraction_result import ExtractionResult
    from app.models.memory import Memory
    from app.models.raw_message import RawMessage


class MemorySource(Base, UUIDMixin, TimestampMixin):
    """Provenance: which raw message supports a memory, through which extraction result.

    The relation is many-to-many. One memory can rest on several messages, and one
    message can support several memories. ``extraction_result_id`` is empty when the
    user, not an extraction, tied the message to the memory (saving a memory from a
    message the pipeline held back).
    """

    __tablename__ = "memory_sources"

    memory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="RESTRICT"), nullable=False
    )
    raw_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_messages.id", ondelete="RESTRICT"), nullable=False
    )
    extraction_result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_results.id", ondelete="RESTRICT"), nullable=True
    )
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_role: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        CheckConstraint(enum_check("source_role", SourceRole), name="valid_source_role"),
        UniqueConstraint(
            "memory_id",
            "raw_message_id",
            "extraction_result_id",
            name="uq_memory_sources_memory_message_extraction",
        ),
        Index("ix_memory_sources_memory_id", "memory_id"),
        Index("ix_memory_sources_raw_message_id", "raw_message_id"),
        Index("ix_memory_sources_extraction_result_id", "extraction_result_id"),
        # The unique constraint above treats NULLs as distinct; this covers sources the
        # user linked.
        Index(
            "uq_memory_sources_memory_message_by_user",
            "memory_id",
            "raw_message_id",
            unique=True,
            postgresql_where=text("extraction_result_id IS NULL"),
        ),
    )

    memory: Mapped["Memory"] = relationship("Memory", back_populates="sources")
    raw_message: Mapped["RawMessage"] = relationship("RawMessage", back_populates="memory_sources")
    extraction_result: Mapped["ExtractionResult | None"] = relationship(
        "ExtractionResult", back_populates="memory_sources"
    )
