import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin


class DailyUsage(Base, UUIDMixin, UpdateTimestampMixin):
    """The prompts a user used on one UTC day: chat messages they sent and scheduled runs
    started for them.

    The daily limit is checked and counted in one statement against this row, so it holds
    under concurrent requests and across every process serving the API. A prompt counted
    in a transaction that rolls back is not counted. Deleted with the user's account.
    """

    __tablename__ = "daily_usage"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    chat_messages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    scheduled_runs: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "day"),
        CheckConstraint("chat_messages >= 0 AND scheduled_runs >= 0", name="non_negative_counts"),
    )

    @property
    def prompts(self) -> int:
        return self.chat_messages + self.scheduled_runs
