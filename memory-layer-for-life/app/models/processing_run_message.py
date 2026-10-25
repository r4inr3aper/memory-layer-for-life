import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.processing_run import ProcessingRun
    from app.models.raw_message import RawMessage


class ProcessingRunMessage(Base, TimestampMixin):
    """Membership of a raw message in a processing unit, with its position in the unit."""

    __tablename__ = "processing_run_messages"

    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT"), primary_key=True
    )
    raw_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_messages.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("position >= 0", name="non_negative_position"),
        UniqueConstraint(
            "processing_run_id", "position", name="uq_processing_run_messages_run_position"
        ),
        Index("ix_processing_run_messages_raw_message_id", "raw_message_id"),
    )

    processing_run: Mapped["ProcessingRun"] = relationship(
        "ProcessingRun", back_populates="messages"
    )
    raw_message: Mapped["RawMessage"] = relationship("RawMessage", back_populates="run_links")
