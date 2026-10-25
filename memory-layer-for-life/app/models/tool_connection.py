import uuid
from datetime import datetime
from typing import Final

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin
from app.db.constraints import members_check
from app.domain.enums import ToolConnectionStatus

STORED_CONNECTION_STATUSES: Final = tuple(
    status for status in ToolConnectionStatus if status is not ToolConnectionStatus.NOT_CONNECTED
)


class ToolConnection(Base, UUIDMixin, UpdateTimestampMixin):
    """A user's connection to one app of the catalog, as last seen in Composio.

    Composio holds the credentials. This row remembers which connected account belongs to
    the user and its last known state, so listings need no call to Composio.
    ``toolkit_slug`` is a key of ``app.domain.tool_catalog``.
    """

    __tablename__ = "tool_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    toolkit_slug: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    composio_connected_account_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    composio_connection_request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    connected_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    connected_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Whether the app's items (calendar events) become memories, and how the last sync
    # went (ADR-047).
    memory_sync_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "toolkit_slug", name="uq_tool_connections_user_toolkit"),
        CheckConstraint(members_check("status", STORED_CONNECTION_STATUSES), name="valid_status"),
    )
