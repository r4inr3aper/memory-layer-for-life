import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.db.base import new_uuid
from app.domain.enums import ToolConnectionStatus
from app.models.tool_connection import ToolConnection
from app.repositories.base import BaseRepository


class ToolConnectionRepository(BaseRepository):
    """Persistence of users' app connections."""

    async def list_for_user(self, user_id: uuid.UUID) -> list[ToolConnection]:
        rows = await self._session.scalars(
            select(ToolConnection).where(ToolConnection.user_id == user_id)
        )
        return list(rows)

    async def get(self, user_id: uuid.UUID, toolkit_slug: str) -> ToolConnection | None:
        result: ToolConnection | None = await self._session.scalar(
            select(ToolConnection).where(
                ToolConnection.user_id == user_id, ToolConnection.toolkit_slug == toolkit_slug
            )
        )
        return result

    async def save(
        self,
        user_id: uuid.UUID,
        toolkit_slug: str,
        *,
        status: ToolConnectionStatus,
        now: datetime,
        connected_account_id: str | None,
        connection_request_id: str | None,
        label: str | None,
        email: str | None,
    ) -> ToolConnection:
        """Write the connection's latest known state, creating the row if needed.

        ``connected_at`` keeps the moment a connection first became connected for as long
        as it stays connected, and is cleared when it stops.
        """
        connected = status is ToolConnectionStatus.CONNECTED
        values = {
            "status": status.value,
            "composio_connected_account_id": connected_account_id,
            "composio_connection_request_id": connection_request_id,
            "connected_label": label,
            "connected_email": email,
            "last_checked_at": now,
            "updated_at": now,
        }
        statement = insert(ToolConnection).values(
            id=new_uuid(),
            user_id=user_id,
            toolkit_slug=toolkit_slug,
            connected_at=now if connected else None,
            created_at=now,
            **values,
        )
        upsert = statement.on_conflict_do_update(
            constraint="uq_tool_connections_user_toolkit",
            set_={
                **values,
                "connected_at": (
                    func.coalesce(ToolConnection.connected_at, statement.excluded.connected_at)
                    if connected
                    else None
                ),
            },
        ).returning(ToolConnection)
        result = await self._session.execute(upsert, execution_options={"populate_existing": True})
        row: ToolConnection = result.scalar_one()
        return row
