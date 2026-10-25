import uuid
from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import delete, or_
from sqlalchemy.dialects.postgresql import insert

from app.models.app_user import AppUser
from app.models.feedback import Feedback
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    """Persistence of signed-in users."""

    async def upsert(
        self,
        user_id: uuid.UUID,
        *,
        email: str | None,
        display_name: str | None,
        now: datetime,
    ) -> None:
        """Create the user, or refresh their email and name when the token changed them.

        Safe under concurrent first requests: the insert and the update are one statement.
        """
        statement = insert(AppUser).values(
            id=user_id,
            email=email,
            display_name=display_name,
            created_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[AppUser.id],
            set_={
                "email": statement.excluded.email,
                "display_name": statement.excluded.display_name,
                "updated_at": now,
            },
            where=or_(
                AppUser.email.is_distinct_from(statement.excluded.email),
                AppUser.display_name.is_distinct_from(statement.excluded.display_name),
            ),
        )
        await self._session.execute(statement)

    async def get(self, user_id: uuid.UUID) -> AppUser | None:
        return await self._session.get(AppUser, user_id)

    async def get_for_update(self, user_id: uuid.UUID) -> AppUser | None:
        return await self._session.get(AppUser, user_id, with_for_update=True)

    async def update_profile(
        self, user: AppUser, changes: Mapping[str, object], *, now: datetime
    ) -> AppUser:
        for field, value in changes.items():
            setattr(user, field, value)
        user.updated_at = now
        await self._session.flush()
        return user

    async def delete(self, user_id: uuid.UUID) -> bool:
        """Delete the user and, by the foreign keys' cascades, everything they own."""
        result = await self._session.execute(delete(AppUser).where(AppUser.id == user_id))
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def add_feedback(self, feedback: Feedback) -> Feedback:
        self._session.add(feedback)
        await self._session.flush()
        return feedback
