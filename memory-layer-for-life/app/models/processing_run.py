import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utc_now
from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import ProcessingStatus

if TYPE_CHECKING:
    from app.models.extraction_result import ExtractionResult
    from app.models.processing_run_event import ProcessingRunEvent
    from app.models.processing_run_message import ProcessingRunMessage
    from app.models.raw_message import RawMessage


class ProcessingRun(Base, UUIDMixin, TimestampMixin):
    """One logical processing operation over an ordered unit of raw messages.

    ``idempotency_key`` is the processing identity: the same unit under the same
    pipeline fingerprint always maps to the same row. Retries reuse the row and
    increment ``attempt_number``. ``raw_message_id`` is the anchor, the first message of
    the unit; the full ordered unit lives in ``processing_run_messages``.
    """

    __tablename__ = "processing_runs"

    raw_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_messages.id", ondelete="RESTRICT"), nullable=False
    )
    pipeline_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ProcessingStatus.QUEUED.value,
        server_default=ProcessingStatus.QUEUED.value,
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="positive_attempt_number"),
        CheckConstraint(enum_check("status", ProcessingStatus), name="valid_status"),
        Index("ix_processing_runs_raw_message_id", "raw_message_id"),
        Index("ix_processing_runs_status", "status"),
        Index("ix_processing_runs_created_at", "created_at"),
        Index("ix_processing_runs_status_available_at", "status", "available_at"),
    )

    anchor_message: Mapped["RawMessage"] = relationship("RawMessage")
    messages: Mapped[list["ProcessingRunMessage"]] = relationship(
        "ProcessingRunMessage",
        back_populates="processing_run",
        order_by="ProcessingRunMessage.position",
    )
    events: Mapped[list["ProcessingRunEvent"]] = relationship(
        "ProcessingRunEvent",
        back_populates="processing_run",
        order_by="ProcessingRunEvent.created_at",
    )
    extraction_result: Mapped["ExtractionResult | None"] = relationship(
        "ExtractionResult", back_populates="processing_run", uselist=False
    )
