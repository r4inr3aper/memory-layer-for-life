import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import InsightKind


class InsightFeedback(Base, UUIDMixin, UpdateTimestampMixin):
    """Whether a user found an insight useful. One row per user and insight key (the key
    names the insight and its period), so a later answer replaces an earlier one. An
    insight marked not useful is not shown again; the rows also measure which kinds of
    insight help people. Deleted with the user."""

    __tablename__ = "insight_feedback"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    insight_key: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    useful: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        CheckConstraint(enum_check("kind", InsightKind), name="valid_kind"),
        CheckConstraint("length(insight_key) > 0", name="non_empty_insight_key"),
        UniqueConstraint("user_id", "insight_key"),
    )
