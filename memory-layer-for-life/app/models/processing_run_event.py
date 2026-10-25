import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.constraints import enum_check, nullable_enum_check
from app.domain.enums import PipelineStage, RunEventType

if TYPE_CHECKING:
    from app.models.processing_run import ProcessingRun


class ProcessingRunEvent(Base, UUIDMixin, TimestampMixin):
    """Append-only audit log of what happened to a processing run.

    A run row holds only its latest state. This log keeps every attempt, so the error of
    an earlier attempt stays inspectable after a retry succeeds. ``detail`` is sanitized:
    it never contains message content or provider payloads.
    """

    __tablename__ = "processing_run_events"

    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="positive_attempt_number"),
        CheckConstraint(enum_check("event_type", RunEventType), name="valid_event_type"),
        CheckConstraint(nullable_enum_check("stage", PipelineStage), name="valid_stage"),
        Index("ix_processing_run_events_run_created", "processing_run_id", "created_at"),
    )

    processing_run: Mapped["ProcessingRun"] = relationship("ProcessingRun", back_populates="events")
