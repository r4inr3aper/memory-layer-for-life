"""Users' connections to apps, through Composio.

Composio is the source of truth for whether a connection works; the
``tool_connections`` row is the last state seen, so the catalog lists without a call to
Composio. Checking a status, connecting, and disconnecting talk to Composio and write
what they learn.

A user may have connected the same app more than once. Any active account of the
toolkit counts as connected, and disconnecting removes all of them, because the
assistant would otherwise keep using whichever one is left.

Connecting needs a Composio auth config for the app's toolkit. Auth configs belong to the
Composio project, so none is in the code: the operator's ``COMPOSIO_AUTH_CONFIGS`` entry
is used, else the project's own auth config for the toolkit, else one created with
Composio's managed sign-in on the first connect. The result is remembered per app for
the life of the process.
"""

import asyncio
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.session import transaction
from app.domain.enums import ToolConnectionStatus
from app.domain.errors import IntegrationError, IntegrationNotConfiguredError, RecordNotFoundError
from app.domain.principal import Principal
from app.domain.tool_catalog import TOOL_CATALOG, ToolSpec, find_tool
from app.integrations.composio import (
    SERVICE_NAME,
    ComposioAccount,
    ComposioClient,
    ComposioNotFoundError,
    ComposioRejectedError,
)
from app.models.tool_connection import ToolConnection
from app.repositories.tool_connection_repository import ToolConnectionRepository

logger = structlog.get_logger(__name__)

_STATUS_BY_COMPOSIO_STATE: Final[dict[str, ToolConnectionStatus]] = {
    "ACTIVE": ToolConnectionStatus.CONNECTED,
    "CONNECTED": ToolConnectionStatus.CONNECTED,
    "SUCCESS": ToolConnectionStatus.CONNECTED,
    "INITIATED": ToolConnectionStatus.PENDING,
    "INITIALIZING": ToolConnectionStatus.PENDING,
    "PENDING": ToolConnectionStatus.PENDING,
    "FAILED": ToolConnectionStatus.FAILED,
    "ERROR": ToolConnectionStatus.FAILED,
    "REVOKED": ToolConnectionStatus.REVOKED,
    "EXPIRED": ToolConnectionStatus.REVOKED,
    "DISABLED": ToolConnectionStatus.REVOKED,
    "INACTIVE": ToolConnectionStatus.REVOKED,
}


def connection_status(composio_state: str) -> ToolConnectionStatus:
    return _STATUS_BY_COMPOSIO_STATE.get(composio_state.upper(), ToolConnectionStatus.PENDING)


@dataclass(frozen=True, slots=True)
class ToolView:
    """One catalog app and the user's connection to it, if any."""

    spec: ToolSpec
    status: ToolConnectionStatus
    connection: ToolConnection | None


@dataclass(frozen=True, slots=True)
class StartedConnection:
    """``connect_url`` is absent when the app turned out to be connected already."""

    view: ToolView
    connect_url: str | None


class ToolConnectionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        composio: ComposioClient | None,
        *,
        auth_config_overrides: Mapping[str, str],
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._composio = composio
        self._auth_config_overrides = {
            slug.lower(): config for slug, config in auth_config_overrides.items()
        }
        # Auth configs found in or created for the Composio project, by toolkit. One lock
        # per toolkit, so concurrent first connects create one auth config, not several.
        self._auth_configs: dict[str, str] = {}
        self._auth_config_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._clock = clock

    @property
    def available(self) -> bool:
        return self._composio is not None

    async def list_tools(self, principal: Principal) -> list[ToolView]:
        async with self._session_factory() as session:
            rows = await ToolConnectionRepository(session).list_for_user(principal.id)
        by_slug = {row.toolkit_slug: row for row in rows}
        return [_view(spec, by_slug.get(spec.slug)) for spec in TOOL_CATALOG]

    async def start_connection(
        self, principal: Principal, slug: str, *, callback_url: str | None
    ) -> StartedConnection:
        spec = _spec(slug)
        composio = self._require()
        user_id = str(principal.id)

        active = self._matching(await composio.list_active_accounts(user_id), spec)
        if active:
            view = await self._save_connected(principal, spec, active[0])
            return StartedConnection(view=view, connect_url=None)

        auth_config_id = await self._auth_config_id(composio, spec)
        try:
            link = await composio.link_account(user_id, auth_config_id, callback_url=callback_url)
        except ComposioNotFoundError as error:
            if spec.slug in self._auth_config_overrides:
                raise IntegrationError(
                    SERVICE_NAME,
                    f"has no auth config {auth_config_id}, set for {spec.name} in "
                    "COMPOSIO_AUTH_CONFIGS.",
                ) from error
            # The auth config was deleted in Composio since it was looked up: look again.
            if self._auth_configs.get(spec.slug) == auth_config_id:
                del self._auth_configs[spec.slug]
            auth_config_id = await self._auth_config_id(composio, spec)
            link = await composio.link_account(user_id, auth_config_id, callback_url=callback_url)
        async with transaction(self._session_factory) as session:
            row = await ToolConnectionRepository(session).save(
                principal.id,
                spec.slug,
                status=ToolConnectionStatus.PENDING,
                now=self._clock(),
                connected_account_id=link.connected_account_id,
                connection_request_id=link.request_id,
                label=None,
                email=None,
            )
        logger.info("tool_connection_started", toolkit=spec.slug)
        return StartedConnection(view=_view(spec, row), connect_url=link.redirect_url)

    async def refresh_status(self, principal: Principal, slug: str) -> ToolView:
        """Ask Composio for the connection's current state and remember it."""
        spec = _spec(slug)
        composio = self._require()

        active = self._matching(await composio.list_active_accounts(str(principal.id)), spec)
        if active:
            return await self._save_connected(principal, spec, active[0])

        async with self._session_factory() as session:
            row = await ToolConnectionRepository(session).get(principal.id, spec.slug)
        if row is None:
            return _view(spec, None)

        status = ToolConnectionStatus(row.status)
        account_id = row.composio_connected_account_id
        label, email = row.connected_label, row.connected_email
        lookup_id = row.composio_connected_account_id or row.composio_connection_request_id
        if lookup_id is not None:
            try:
                account = await composio.get_account(lookup_id)
            except ComposioNotFoundError:
                status = ToolConnectionStatus.REVOKED
                account_id = None
            else:
                status = connection_status(account.status)
                account_id = account.id
                label = account.label or label
                email = account.email or email

        async with transaction(self._session_factory) as session:
            saved = await ToolConnectionRepository(session).save(
                principal.id,
                spec.slug,
                status=status,
                now=self._clock(),
                connected_account_id=account_id,
                connection_request_id=row.composio_connection_request_id,
                label=label,
                email=email,
            )
        return _view(spec, saved)

    async def disconnect(self, principal: Principal, slug: str) -> ToolView:
        """Remove every connected account of the app in Composio, then mark it revoked.

        If Composio refuses, nothing is marked: the account would still work, and saying
        otherwise would mislead the user.
        """
        spec = _spec(slug)
        composio = self._require()

        async with self._session_factory() as session:
            row = await ToolConnectionRepository(session).get(principal.id, spec.slug)
        account_ids = {
            account.id
            for account in self._matching(
                await composio.list_active_accounts(str(principal.id)), spec
            )
        }
        if row is not None and row.composio_connected_account_id is not None:
            account_ids.add(row.composio_connected_account_id)

        for account_id in sorted(account_ids):
            try:
                await composio.delete_account(account_id)
            except ComposioNotFoundError:
                continue

        async with transaction(self._session_factory) as session:
            saved = await ToolConnectionRepository(session).save(
                principal.id,
                spec.slug,
                status=ToolConnectionStatus.REVOKED,
                now=self._clock(),
                connected_account_id=None,
                connection_request_id=None,
                label=None,
                email=None,
            )
        logger.info("tool_connection_revoked", toolkit=spec.slug, accounts=len(account_ids))
        return _view(spec, saved)

    async def last_connected(self, principal: Principal) -> list[str]:
        """Toolkits the user's apps were connected to when last seen, as the app lists
        them, without a call to Composio. Empty when Composio is not configured, since no
        app can be used then."""
        if self._composio is None:
            return []
        async with self._session_factory() as session:
            rows = await ToolConnectionRepository(session).list_for_user(principal.id)
        return sorted(
            row.toolkit_slug for row in rows if row.status == ToolConnectionStatus.CONNECTED.value
        )

    async def active_accounts(self, principal: Principal) -> dict[str, list[str]]:
        """Connected account ids per toolkit, straight from Composio."""
        composio = self._require()
        accounts: dict[str, list[str]] = {}
        for account in await composio.list_active_accounts(str(principal.id)):
            if account.toolkit_slug is not None:
                accounts.setdefault(account.toolkit_slug, []).append(account.id)
        return accounts

    async def revoke_all(self, principal: Principal) -> tuple[int, int]:
        """Delete every connected account the user has in Composio, for account deletion.

        Returns how many were removed and how many could not be. Nothing is written here:
        the user's rows are about to be deleted.
        """
        if self._composio is None:
            return 0, 0
        removed = failed = 0
        for account in await self._composio.list_active_accounts(str(principal.id)):
            try:
                await self._composio.delete_account(account.id)
            except ComposioNotFoundError:
                removed += 1
            except IntegrationError:
                failed += 1
                logger.warning("tool_connection_revoke_failed", account_id=account.id)
            else:
                removed += 1
        return removed, failed

    # --- Helpers -------------------------------------------------------------------

    def _require(self) -> ComposioClient:
        if self._composio is None:
            raise IntegrationNotConfiguredError(SERVICE_NAME, "COMPOSIO_API_KEY")
        return self._composio

    async def _auth_config_id(self, composio: ComposioClient, spec: ToolSpec) -> str:
        """The auth config the connect flow uses for the app (see the module docstring)."""
        configured = self._auth_config_overrides.get(spec.slug)
        if configured is not None:
            return configured
        async with self._auth_config_locks[spec.slug]:
            known = self._auth_configs.get(spec.slug)
            if known is None:
                known = await composio.find_auth_config(spec.slug)
                if known is None:
                    known = await self._create_managed_auth_config(composio, spec)
                self._auth_configs[spec.slug] = known
            return known

    async def _create_managed_auth_config(self, composio: ComposioClient, spec: ToolSpec) -> str:
        try:
            created = await composio.create_managed_auth_config(spec.slug)
        except ComposioRejectedError as error:
            raise IntegrationError(
                SERVICE_NAME,
                f"could not set up sign-in for {spec.name} (HTTP {error.http_status}). Create "
                "an auth config for it in Composio, or add one to COMPOSIO_AUTH_CONFIGS.",
            ) from error
        logger.info("composio_auth_config_created", toolkit=spec.slug)
        return created

    def _matching(self, accounts: list[ComposioAccount], spec: ToolSpec) -> list[ComposioAccount]:
        """Active accounts that belong to the app: of its toolkit, or made with its auth
        config when Composio did not name the toolkit."""
        known = self._auth_config_overrides.get(spec.slug) or self._auth_configs.get(spec.slug)
        return [
            account
            for account in accounts
            if account.toolkit_slug == spec.slug
            or (known is not None and account.auth_config_id == known)
        ]

    async def _save_connected(
        self, principal: Principal, spec: ToolSpec, account: ComposioAccount
    ) -> ToolView:
        async with transaction(self._session_factory) as session:
            row = await ToolConnectionRepository(session).save(
                principal.id,
                spec.slug,
                status=ToolConnectionStatus.CONNECTED,
                now=self._clock(),
                connected_account_id=account.id,
                connection_request_id=None,
                label=account.label,
                email=account.email,
            )
        return _view(spec, row)


def _spec(slug: str) -> ToolSpec:
    spec = find_tool(slug)
    if spec is None:
        raise RecordNotFoundError("App", slug)
    return spec


def _view(spec: ToolSpec, row: ToolConnection | None) -> ToolView:
    status = (
        ToolConnectionStatus(row.status)
        if row is not None
        else (ToolConnectionStatus.NOT_CONNECTED)
    )
    return ToolView(spec=spec, status=status, connection=row)
