import uuid
from typing import Any

from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import ChatRole

# The message as full-text search sees it, like memories: stemmed English words weighted
# above the exact words, so names and other languages still match. Kept by PostgreSQL.
SEARCH_DOCUMENT_SQL = (
    "setweight(to_tsvector('english'::regconfig, content), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, content), 'B')"
)


class ChatMessage(Base, UUIDMixin, UpdateTimestampMixin):
    """One message in a thread.

    The server writes both sides of a conversation: the user's message when a turn starts
    and the assistant's reply when it ends. ``metadata`` carries what the app renders
    beside the text, validated by ``app.schemas.chat.MessageMetadata``: a browser preview,
    an app connection link, a schedule proposal, or the result of a scheduled run.
    """

    __tablename__ = "chat_messages"

    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    # Generated from ``content``; never written and never loaded, only searched.
    search_document: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(SEARCH_DOCUMENT_SQL, persisted=True), nullable=True, deferred=True
    )

    __table_args__ = (
        CheckConstraint(enum_check("role", ChatRole), name="valid_role"),
        CheckConstraint("length(content) > 0", name="non_empty_content"),
        Index("ix_chat_messages_thread_id_created_at", "thread_id", "created_at"),
        Index("ix_chat_messages_search_document", "search_document", postgresql_using="gin"),
    )
