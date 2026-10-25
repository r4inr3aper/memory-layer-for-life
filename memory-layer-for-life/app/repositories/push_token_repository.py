import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.db.base import new_uuid
from app.domain.enums import DevicePlatform
from app.models.push_token import PushToken
from app.repositories.base import BaseRepository


class PushTokenRepository(BaseRepository):
    async def register(
        self, user_id: uuid.UUID, token: str, platform: DevicePlatform, *, now: datetime
    ) -> None:
        """Store the device's token for this user. A token seen before moves to them."""
        statement = insert(PushToken).values(
            id=new_uuid(),
            user_id=user_id,
            token=token,
            platform=platform.value,
            created_at=now,
            updated_at=now,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[PushToken.token],
                set_={"user_id": user_id, "platform": platform.value, "updated_at": now},
            )
        )

    async def unregister(self, user_id: uuid.UUID, token: str) -> None:
        await self._session.execute(
            delete(PushToken).where(PushToken.user_id == user_id, PushToken.token == token)
        )

    async def tokens_for(self, user_id: uuid.UUID) -> list[str]:
        rows = await self._session.scalars(
            select(PushToken.token).where(PushToken.user_id == user_id).order_by(PushToken.token)
        )
        return list(rows)

    async def forget(self, tokens: Sequence[str]) -> None:
        """Delete tokens the push service reported as no longer registered."""
        if tokens:
            await self._session.execute(delete(PushToken).where(PushToken.token.in_(tokens)))
