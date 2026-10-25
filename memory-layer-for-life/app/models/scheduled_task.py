import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin
from app.db.constraints import enum_check, members_check
from app.domain.enums import (
    ScheduleDelivery,
    ScheduleFrequency,
    ScheduleRunStatus,
    ScheduleStatus,
    Weekday,
)

FINISHED_RUN_STATUSES = (
    ScheduleRunStatus.SUCCEEDED,
    ScheduleRunStatus.FAILED,
    ScheduleRunStatus.SKIPPED,
)
_WEEKDAYS = ",".join(f"'{weekday.value}'" for weekday in Weekday)


class ScheduledTask(Base, UUIDMixin, UpdateTimestampMixin):
    """A task the assistant runs on a schedule the user confirmed.

    ``original_prompt`` is what the user wrote; ``task`` is the instruction the assistant
    executes. The rule is a wall-clock time in ``timezone`` with a frequency and the fields
    that frequency needs (``app.domain.schedule_rules``); check constraints keep each
    frequency's fields present and the others empty. ``next_run_at`` is the next slot in
    UTC. The dispatcher claims a due slot and moves ``next_run_at`` on in the same
    transaction, so each slot is taken once; a one-time schedule then has none and is
    ``completed``.

    ``last_run_*`` copy the outcome of the latest finished run, for listing.
    """

    __tablename__ = "scheduled_tasks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    source_thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_threads.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    original_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)

    frequency: Mapped[str] = mapped_column(String(10), nullable=False)
    local_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    # Weekly: the weekdays it runs on, in weekday order.
    weekdays: Mapped[list[str] | None] = mapped_column(ARRAY(String(10)), nullable=True)
    # Monthly: 1 to 31; a shorter month runs on its last day.
    day_of_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Once: the day it runs. Interval: the day of its first run.
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Interval: hours between runs.
    interval_hours: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)

    delivery: Mapped[str] = mapped_column(String(20), nullable=False)
    # Where the delivery goes inside the app, such as a Slack channel or an address.
    delivery_target: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=ScheduleStatus.ACTIVE.value,
        server_default=ScheduleStatus.ACTIVE.value,
    )
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    last_run_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(enum_check("frequency", ScheduleFrequency), name="valid_frequency"),
        CheckConstraint(
            "weekdays IS NULL OR (cardinality(weekdays) BETWEEN 1 AND 7 "
            f"AND weekdays <@ ARRAY[{_WEEKDAYS}]::varchar[])",
            name="valid_weekdays",
        ),
        CheckConstraint(
            "(frequency = 'weekly') = (weekdays IS NOT NULL)", name="weekly_has_weekdays"
        ),
        CheckConstraint(
            "day_of_month IS NULL OR day_of_month BETWEEN 1 AND 31", name="valid_day_of_month"
        ),
        CheckConstraint(
            "(frequency = 'monthly') = (day_of_month IS NOT NULL)", name="monthly_has_day"
        ),
        CheckConstraint(
            "(frequency IN ('once','interval')) = (start_date IS NOT NULL)",
            name="dated_has_start_date",
        ),
        CheckConstraint(
            "interval_hours IS NULL OR interval_hours BETWEEN 1 AND 24",
            name="valid_interval_hours",
        ),
        CheckConstraint(
            "(frequency = 'interval') = (interval_hours IS NOT NULL)",
            name="interval_has_hours",
        ),
        CheckConstraint(enum_check("delivery", ScheduleDelivery), name="valid_delivery"),
        CheckConstraint(enum_check("status", ScheduleStatus), name="valid_status"),
        CheckConstraint(
            f"last_run_status IS NULL OR {members_check('last_run_status', FINISHED_RUN_STATUSES)}",
            name="valid_last_run_status",
        ),
        CheckConstraint(
            "status <> 'active' OR next_run_at IS NOT NULL", name="active_has_next_run"
        ),
        CheckConstraint(
            "status NOT IN ('cancelled','completed') OR next_run_at IS NULL",
            name="ended_has_no_next_run",
        ),
        CheckConstraint("status <> 'completed' OR frequency = 'once'", name="only_once_completes"),
        CheckConstraint("length(title) > 0", name="non_empty_title"),
        CheckConstraint("length(task) > 0", name="non_empty_task"),
        Index(
            "ix_scheduled_tasks_due",
            "next_run_at",
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_scheduled_tasks_user_id_created_at", "user_id", "created_at"),
    )
