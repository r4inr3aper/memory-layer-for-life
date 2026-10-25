import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import ScheduleRunStatus, ScheduleRunTrigger


class ScheduledTaskRun(Base, UUIDMixin, TimestampMixin):
    """One execution of a scheduled task.

    A scheduled run names the slot it serves in ``scheduled_for``, and a unique index
    allows one run per slot, so two dispatchers cannot both run it. A second partial
    unique index allows one running run per task, so a manual run cannot overlap a
    scheduled one. A run is never retried: it may already have sent a message.
    """

    __tablename__ = "scheduled_task_runs"

    scheduled_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=ScheduleRunStatus.RUNNING.value,
        server_default=ScheduleRunStatus.RUNNING.value,
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The chat message that delivered the result, for runs delivered to chat.
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(enum_check("trigger", ScheduleRunTrigger), name="valid_trigger"),
        CheckConstraint(enum_check("status", ScheduleRunStatus), name="valid_status"),
        CheckConstraint(
            "(trigger = 'schedule') = (scheduled_for IS NOT NULL)", name="scheduled_has_slot"
        ),
        CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name="finished_when_not_running"
        ),
        CheckConstraint(
            "status <> 'failed' OR error_code IS NOT NULL", name="failed_has_error_code"
        ),
        Index(
            "uq_scheduled_task_runs_slot",
            "scheduled_task_id",
            "scheduled_for",
            unique=True,
            postgresql_where=text("scheduled_for IS NOT NULL"),
        ),
        Index(
            "uq_scheduled_task_runs_one_running",
            "scheduled_task_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
        Index("ix_scheduled_task_runs_task_id_started_at", "scheduled_task_id", "started_at"),
    )
