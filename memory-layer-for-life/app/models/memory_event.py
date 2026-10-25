import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import MemoryEventAction

if TYPE_CHECKING:
    from app.models.memory import Memory


class MemoryEvent(Base, UUIDMixin, TimestampMixin):
    """Append-only change history of one memory: what its owner did to it and when.

    ``details`` holds what changed, such as the previous text of a correction or the
    other memory of a merge. Deleted with its memory: deleting a memory forgets it,
    history included.
    """

    __tablename__ = "memory_events"

    memory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        CheckConstraint(enum_check("action", MemoryEventAction), name="valid_action"),
        Index("ix_memory_events_memory_created", "memory_id", "created_at"),
    )

    memory: Mapped["Memory"] = relationship("Memory", back_populates="events")
