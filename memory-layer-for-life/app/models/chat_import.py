import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import ImportStatus


class ChatImport(Base, UUIDMixin, UpdateTimestampMixin):
    """A chat export a user brought in to become memories (``app.domain.whatsapp``).

    Uploading reads it and stores its text (``previewed``); the user then says which
    participant they are and how much to import, and its conversations are ingested as
    units for the pipeline (``queued``) and the text is dropped: the raw messages hold it
    from then on. ``file_sha256`` refuses the same file twice. Deleted with the user.
    """

    __tablename__ = "chat_imports"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # [[name, messages, conversations], ...], most messages first.
    participants: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    conversation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Chosen when the import starts.
    owner_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    since: Mapped[date | None] = mapped_column(Date, nullable=True)
    unit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The export's text, until the import starts.
    content: Mapped[str | None] = mapped_column(Text, nullable=True, deferred=True)

    __table_args__ = (
        CheckConstraint(enum_check("status", ImportStatus), name="valid_status"),
        CheckConstraint("source IN ('whatsapp')", name="valid_source"),
        UniqueConstraint("user_id", "file_sha256"),
    )
