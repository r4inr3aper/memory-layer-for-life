"""Deleting a user's account.

Deletion removes everything the user has here and, when possible, everywhere else:

1. Their connected apps are revoked in Composio first, so no third-party access outlives
   the account. An app that cannot be revoked is reported, not hidden.
2. Their memory data is deleted: the memories made from their chats, the entities and
   evidence behind them, and the pipeline's records of it. Then their row is deleted, and
   with it, by the schema's cascades, their threads, messages, schedules, runs, app
   connections, push tokens, feedback, and daily usage. The cost log keeps its other facts
   with the owner cleared.
3. Their Supabase sign-in identity is deleted, when the API holds the project's secret
   key. Without it the data is gone but the identity stays, and the response says so.

Signing in again afterwards starts a new, empty account.
"""

from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import transaction
from app.domain.principal import Principal
from app.integrations.supabase_admin import SupabaseAdminClient
from app.repositories.owned_memory_repository import OwnedMemoryRepository
from app.repositories.user_repository import UserRepository
from app.services.tool_connections import ToolConnectionService
from app.services.users import UserService

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AccountDeletion:
    apps_disconnected: int
    apps_not_disconnected: int
    identity_deleted: bool


class AccountService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        users: UserService,
        connections: ToolConnectionService,
        identity: SupabaseAdminClient | None,
    ) -> None:
        self._session_factory = session_factory
        self._users = users
        self._connections = connections
        self._identity = identity

    async def delete(self, principal: Principal) -> AccountDeletion:
        removed, failed = await self._connections.revoke_all(principal)

        async with transaction(self._session_factory) as session:
            await OwnedMemoryRepository(session).delete_for(principal.id)
            await UserRepository(session).delete(principal.id)
        self._users.forget(principal.id)

        identity_deleted = False
        if self._identity is not None:
            # Raises if Supabase refuses. The data is already gone; asking again repeats
            # only this step, on a fresh, empty account row.
            await self._identity.delete_user(principal.id)
            identity_deleted = True

        logger.info(
            "account_deleted",
            apps_disconnected=removed,
            apps_not_disconnected=failed,
            identity_deleted=identity_deleted,
        )
        return AccountDeletion(
            apps_disconnected=removed,
            apps_not_disconnected=failed,
            identity_deleted=identity_deleted,
        )
