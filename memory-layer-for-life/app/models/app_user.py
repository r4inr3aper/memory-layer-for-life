import uuid
from datetime import date, time

from sqlalchemy import Boolean, CheckConstraint, Date, Integer, String, Time
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UpdateTimestampMixin


class AppUser(Base, UpdateTimestampMixin):
    """A person who signed in to the app through Supabase Auth.

    The id is the Supabase user id (the ``sub`` claim of the access token), so it is never
    generated here. The row is written the first time a user calls the API and keeps the
    email and name from their latest token. Supabase remains the identity provider; this
    row anchors the user's data in this database.
    """

    __tablename__ = "app_users"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # How the user personalized their assistant. Empty means the app's defaults.
    assistant_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    assistant_subtitle: Mapped[str | None] = mapped_column(String(60), nullable=True)
    assistant_icon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    assistant_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Push notifications for finished scheduled runs.
    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Whether the user's chat messages become memories.
    memory_capture_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # This user's prompts per day, overriding ASSISTANT_DAILY_PROMPT_LIMIT. Set by an
    # operator, never by the app. Empty means the default; 0 means unlimited.
    daily_prompt_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The user's IANA timezone, as the app last reported it. Empty: DEFAULT_TIMEZONE.
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # A daily brief at ``brief_time`` local time; ``last_brief_on`` is the local day the
    # last one went, so each day gets at most one.
    brief_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    brief_time: Mapped[time] = mapped_column(
        Time(timezone=False), nullable=False, default=time(8, 0), server_default="08:00"
    )
    last_brief_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Push for reminders the user set.
    reminders_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # No push for the brief between these local times (may wrap past midnight).
    quiet_hours_start: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "assistant_name IS NULL OR length(trim(assistant_name)) > 0",
            name="assistant_name_not_blank",
        ),
        CheckConstraint(
            "daily_prompt_limit IS NULL OR daily_prompt_limit >= 0",
            name="non_negative_daily_prompt_limit",
        ),
        CheckConstraint(
            "(quiet_hours_start IS NULL) = (quiet_hours_end IS NULL)",
            name="quiet_hours_complete",
        ),
    )
