import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    ColumnElement,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin
from app.db.constraints import enum_check, nullable_enum_check
from app.domain.enums import CloseReason, MemoryOrigin, MemoryStatus, MemoryType, Sensitivity

# The memory's text as PostgreSQL full-text search sees it: stemmed English words, so
# "bills" finds "bill", weighted above the same text unstemmed ('simple'), so names, codes,
# and words in other languages still match exactly. Kept by PostgreSQL itself.
SEARCH_DOCUMENT_SQL = (
    "setweight(to_tsvector('english'::regconfig, content), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, content), 'B')"
)

if TYPE_CHECKING:
    from app.models.memory_entity import MemoryEntity
    from app.models.memory_event import MemoryEvent
    from app.models.memory_relation import MemoryRelation
    from app.models.memory_source import MemorySource


class Memory(Base, UUIDMixin, UpdateTimestampMixin):
    """Common representation of a piece of structured knowledge.

    ``status`` is the lifecycle of the record. Whether the thing described is pending or
    done lives in ``metadata``. ``valid_from`` / ``valid_until`` are when the content is
    believed to apply and are independent of when it was ingested.

    ``origin_extraction_result_id`` and ``origin_ordinal`` identify the extraction output
    a pipeline-built memory came from. Their unique constraint makes it impossible to
    create the same memory twice from one extraction result. Both are NULL for memories
    created by other means.

    ``created_by`` is who wrote the text: the pipeline, or the user (by hand, or by
    correcting a memory, which makes a new version that supersedes the old one).

    Life state (``app.domain.life_state``): ``due_on`` is when an item is due (the
    extractor's resolved date or the user's), ``remind_at`` when to remind the user (cleared
    once sent), and ``closed_at`` with ``close_reason`` when and why an open item stopped
    being open.
    """

    __tablename__ = "memories"

    memory_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=MemoryStatus.PROPOSED.value,
        server_default=MemoryStatus.PROPOSED.value,
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2, asdecimal=False), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_memory_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memories.id", ondelete="RESTRICT"), nullable=True
    )
    origin_extraction_result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_results.id", ondelete="RESTRICT"), nullable=True
    )
    origin_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    # The app user whose chats this came from. Empty for the operator's own memory store
    # (the console and imports). Everything derived from a message has its owner.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=MemoryOrigin.PIPELINE.value,
        server_default=MemoryOrigin.PIPELINE.value,
    )
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Generated from ``content``; never written and never loaded, only searched.
    search_document: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(SEARCH_DOCUMENT_SQL, persisted=True), nullable=True, deferred=True
    )

    __table_args__ = (
        CheckConstraint("supersedes_memory_id != id", name="no_self_supersede"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="valid_memory_confidence",
        ),
        CheckConstraint(enum_check("memory_type", MemoryType), name="valid_memory_type"),
        CheckConstraint(enum_check("status", MemoryStatus), name="valid_memory_status"),
        CheckConstraint(enum_check("created_by", MemoryOrigin), name="valid_created_by"),
        CheckConstraint(
            nullable_enum_check("close_reason", CloseReason), name="valid_close_reason"
        ),
        CheckConstraint("(closed_at IS NULL) = (close_reason IS NULL)", name="closed_has_reason"),
        CheckConstraint("length(content) > 0", name="non_empty_content"),
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
            name="valid_period_order",
        ),
        CheckConstraint(
            "(origin_extraction_result_id IS NULL) = (origin_ordinal IS NULL)",
            name="origin_pair_complete",
        ),
        CheckConstraint(
            "origin_ordinal IS NULL OR origin_ordinal >= 0", name="non_negative_origin_ordinal"
        ),
        UniqueConstraint(
            "origin_extraction_result_id", "origin_ordinal", name="uq_memories_origin"
        ),
        Index("ix_memories_memory_type", "memory_type"),
        Index("ix_memories_status", "status"),
        Index("ix_memories_owner_id_created_at", "owner_id", "created_at"),
        Index("ix_memories_owner_id_due_on", "owner_id", "due_on"),
        Index(
            "ix_memories_remind_at",
            "remind_at",
            postgresql_where=text("remind_at IS NOT NULL"),
        ),
        Index("ix_memories_search_document", "search_document", postgresql_using="gin"),
        # Trigram index, so memories saying nearly the same thing are found for review
        # without comparing every pair (pg_trgm).
        Index(
            "ix_memories_normalized_content_trgm",
            "normalized_content",
            postgresql_using="gin",
            postgresql_ops={"normalized_content": "gin_trgm_ops"},
        ),
    )

    supersedes: Mapped["Memory | None"] = relationship("Memory", remote_side="Memory.id")
    sources: Mapped[list["MemorySource"]] = relationship("MemorySource", back_populates="memory")
    memory_entities: Mapped[list["MemoryEntity"]] = relationship(
        "MemoryEntity", back_populates="memory"
    )
    events: Mapped[list["MemoryEvent"]] = relationship(
        "MemoryEvent", back_populates="memory", passive_deletes=True
    )
    outgoing_relations: Mapped[list["MemoryRelation"]] = relationship(
        "MemoryRelation",
        foreign_keys="MemoryRelation.source_memory_id",
        back_populates="source_memory",
    )
    incoming_relations: Mapped[list["MemoryRelation"]] = relationship(
        "MemoryRelation",
        foreign_keys="MemoryRelation.target_memory_id",
        back_populates="target_memory",
    )


def is_sensitive() -> ColumnElement[bool]:
    """Memories marked sensitive (``metadata.sensitivity``). They are shown to their owner
    but never given to a model: not to the assistant, the embedder, or the reranker."""
    level = func.coalesce(Memory.metadata_["sensitivity"].astext, Sensitivity.NORMAL.value)
    return level == Sensitivity.SENSITIVE.value
