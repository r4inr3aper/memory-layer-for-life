import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import ThreadKind


class ChatThread(Base, UUIDMixin, UpdateTimestampMixin):
    """A conversation with the assistant.

    Each user has one main thread, enforced by a partial unique index, and any number of
    side threads. ``updated_at`` moves forward whenever a message is added, so threads
    sort by recent activity.
    """

    __tablename__ = "chat_threads"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Set while an assistant reply runs in the thread, by whichever process runs it. A
    # second reply is refused until it is cleared or expires.
    turn_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The time of the last message the memory pipeline has seen in this thread. Once the
    # thread goes quiet, what came after it is captured as one unit (ADR-048). Moving it
    # never moves ``updated_at``.
    memory_captured_through: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Whether the model named the thread from its conversation; such a title stays.
    title_generated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    __table_args__ = (
        CheckConstraint(enum_check("kind", ThreadKind), name="valid_kind"),
        CheckConstraint("length(title) > 0", name="non_empty_title"),
        Index(
            "uq_chat_threads_one_main_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'main'"),
        ),
        Index("ix_chat_threads_user_id_updated_at", "user_id", "updated_at"),
    )
