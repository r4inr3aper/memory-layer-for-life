import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import DevicePlatform


class PushToken(Base, UUIDMixin, UpdateTimestampMixin):
    """An Expo push token of one of the user's devices.

    A token identifies a device install, so it belongs to whoever signed in on it last:
    registering it again moves it to the new user. Tokens Expo reports as no longer
    registered are deleted.
    """

    __tablename__ = "push_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    platform: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        CheckConstraint(enum_check("platform", DevicePlatform), name="valid_platform"),
        CheckConstraint("length(token) > 0", name="non_empty_token"),
        Index("ix_push_tokens_user_id", "user_id"),
    )
