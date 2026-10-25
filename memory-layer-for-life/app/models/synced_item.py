import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin


class SyncedItem(Base, UUIDMixin, UpdateTimestampMixin):
    """An item of a connected app (a calendar event) and the memory made from it.

    ``external_updated`` is the app's own version of the item, so a changed event updates
    its memory and an unchanged one is left alone. When the user deletes the memory,
    ``memory_id`` becomes empty and the row stays, so the item is not brought back.
    Deleted with the user.
    """

    __tablename__ = "synced_items"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_updated: Mapped[str | None] = mapped_column(String(64), nullable=True)
    memory_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("user_id", "source", "external_id"),
        # Deleting a memory empties its row here.
        Index("ix_synced_items_memory_id", "memory_id"),
    )
