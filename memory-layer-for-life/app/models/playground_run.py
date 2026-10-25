from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import PlaygroundRunStatus


class PlaygroundRun(Base, UUIDMixin, TimestampMixin):
    """One test call made from the console: what was sent and what came back.

    A playground run is a dry run. It calls the model and applies the same checks the
    pipeline applies, but it creates no raw message, no memory, and no entity. The text
    typed for the test and the model's answer are kept here so a test can be reopened.

    ``output`` is the validated and finalized extraction. ``raw_output`` is the text the
    model returned, kept even when it failed validation.
    """

    __tablename__ = "playground_runs"

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PlaygroundRunStatus.RUNNING.value,
        server_default=PlaygroundRunStatus.RUNNING.value,
    )
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    timezone_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_model: Mapped[str] = mapped_column(String(100), nullable=False)
    effort: Mapped[str] = mapped_column(String(10), nullable=False)

    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrections: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(enum_check("status", PlaygroundRunStatus), name="valid_status"),
        CheckConstraint("jsonb_array_length(messages) > 0", name="has_messages"),
        CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name="finished_when_not_running"
        ),
        CheckConstraint("status <> 'succeeded' OR output IS NOT NULL", name="succeeded_has_output"),
        CheckConstraint(
            "status <> 'failed' OR error_code IS NOT NULL", name="failed_has_error_code"
        ),
        Index("ix_playground_runs_created_at", "created_at"),
    )
