"""Signed-in users.

Supabase is the identity provider. The first request of a user writes their row here,
so their threads, schedules, and connections have an owner to reference; later requests
refresh the email and name when the token carries new ones.
"""

import uuid
from collections.abc import Mapping
from datetime import time
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.errors import RecordNotFoundError
from app.domain.principal import Principal
from app.models.app_user import AppUser
from app.models.feedback import Feedback
from app.repositories.user_repository import UserRepository

# Users whose row is known to be current. Bounded, so a long-lived process cannot grow
# without limit; clearing it only costs one upsert per user.
_MAX_REMEMBERED_USERS: Final = 10_000
PROFILE_FIELDS: Final = frozenset(
    {
        "assistant_name",
        "assistant_subtitle",
        "assistant_icon",
        "assistant_color",
        "notifications_enabled",
        "memory_capture_enabled",
        "timezone",
        "brief_enabled",
        "brief_time",
        "reminders_enabled",
        "quiet_hours_start",
        "quiet_hours_end",
    }
)
# Fields sent as HH:MM and stored as times.
_TIME_FIELDS: Final = frozenset({"brief_time", "quiet_hours_start", "quiet_hours_end"})


class UserService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, clock: Clock = utc_now
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._current: set[Principal] = set()

    async def ensure(self, principal: Principal) -> None:
        """Make sure the user's row exists and matches their token."""
        if principal in self._current:
            return
        async with transaction(self._session_factory) as session:
            await UserRepository(session).upsert(
                principal.id,
                email=principal.email,
                display_name=principal.display_name,
                now=self._clock(),
            )
        if len(self._current) >= _MAX_REMEMBERED_USERS:
            self._current.clear()
        self._current.add(principal)

    async def get(self, principal: Principal) -> AppUser:
        async with self._session_factory() as session:
            user = await UserRepository(session).get(principal.id)
        if user is None:
            raise RecordNotFoundError("User", str(principal.id))
        return user

    async def update_profile(
        self, principal: Principal, changes: Mapping[str, str | bool | None]
    ) -> AppUser:
        """Change how the user personalized the assistant, their timezone, or their
        notification preferences.

        ``changes`` holds only the fields to change; a text field set to None goes back to
        the app's default. Times arrive as HH:MM.
        """
        unknown = set(changes) - PROFILE_FIELDS
        if unknown:
            raise ValueError(f"not profile fields: {sorted(unknown)}")
        values: dict[str, object] = {
            field: _parse_time(value) if field in _TIME_FIELDS else value
            for field, value in changes.items()
        }
        async with transaction(self._session_factory) as session:
            users = UserRepository(session)
            user = await users.get_for_update(principal.id)
            if user is None:
                raise RecordNotFoundError("User", str(principal.id))
            return await users.update_profile(user, values, now=self._clock())

    async def submit_feedback(
        self,
        principal: Principal,
        *,
        message: str,
        platform: str | None,
        app_version: str | None,
    ) -> Feedback:
        async with transaction(self._session_factory) as session:
            return await UserRepository(session).add_feedback(
                Feedback(
                    id=new_uuid(),
                    user_id=principal.id,
                    message=message.strip(),
                    platform=platform,
                    app_version=app_version,
                    created_at=self._clock(),
                )
            )

    def forget(self, user_id: uuid.UUID) -> None:
        """Drop the user from the cache of known rows, after their row was deleted."""
        self._current = {known for known in self._current if known.id != user_id}


def _parse_time(value: object) -> time | None:
    if value is None:
        return None
    hours, minutes = str(value).split(":")
    return time(int(hours), int(minutes))
