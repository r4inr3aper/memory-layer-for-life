import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utc_now
from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.entity_mention import EntityMention
    from app.models.memory_source import MemorySource
    from app.models.processing_run_message import ProcessingRunMessage


class RawMessage(Base, UUIDMixin, TimestampMixin):
    """Immutable source evidence.

    Rows are never updated: a database trigger rejects any UPDATE, and foreign keys from
    derived records use RESTRICT so evidence cannot be deleted from under them.
    """

    __tablename__ = "raw_messages"

    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    # The app user whose chats this came from. Empty for the operator's own memory store
    # (the console and imports). Everything derived from a message has its owner.
    # Deleting the user deletes these first (AccountService), so the key restricts.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "source", "source_message_id", name="uq_raw_messages_source_source_message_id"
        ),
        Index("ix_raw_messages_owner_id", "owner_id"),
        CheckConstraint("length(content) > 0", name="non_empty_content"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="valid_content_sha256"),
        Index("ix_raw_messages_source", "source"),
        Index("ix_raw_messages_ingested_at", "ingested_at"),
        Index("ix_raw_messages_source_created_at", "source_created_at"),
    )

    run_links: Mapped[list["ProcessingRunMessage"]] = relationship(
        "ProcessingRunMessage", back_populates="raw_message"
    )
    entity_mentions: Mapped[list["EntityMention"]] = relationship(
        "EntityMention", back_populates="raw_message"
    )
    memory_sources: Mapped[list["MemorySource"]] = relationship(
        "MemorySource", back_populates="raw_message"
    )
