"""Composio's REST API: connected accounts, the connect flow, and tool execution.

Composio holds each user's app credentials. The application refers to a user by their
Supabase id, which is also their Composio user id.

Tools run through a Tool Router session scoped to one toolkit and to the user's
connected accounts for it: the session searches the toolkit for tools that fit a use
case, then executes one with arguments.

Responses are parsed leniently, because Composio adds fields over time, but every value
the application relies on is checked. Composio's own error text can echo request data,
so failures are described in the application's words.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import httpx
import structlog

from app.domain.errors import IntegrationError

logger = structlog.get_logger(__name__)

SERVICE_NAME: Final = "Composio"
_API: Final = "/api/v3.1"
# Arguments and use cases are cut to the sizes the search endpoint accepts.
_MAX_USE_CASE_CHARS: Final = 1024
_MAX_KNOWN_FIELDS_CHARS: Final = 500
_MAX_ACCOUNTS_PER_TOOLKIT: Final = 5
_ACTIVE: Final = "ACTIVE"

JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ComposioAccount:
    id: str
    status: str
    toolkit_slug: str | None
    auth_config_id: str | None
    label: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class ComposioLink:
    """A started connect flow. The user opens ``redirect_url`` to authorize the app."""

    request_id: str
    redirect_url: str
    connected_account_id: str | None


@dataclass(frozen=True, slots=True)
class ComposioToolMatch:
    slug: str
    description: str | None
    input_schema: JsonObject | None


@dataclass(frozen=True, slots=True)
class ComposioExecution:
    successful: bool
    data: object
    error: str | None


class ComposioNotFoundError(IntegrationError):
    """Composio does not know the addressed record, for example a deleted account."""

    code = "INTEGRATION_RECORD_NOT_FOUND"


class ComposioRejectedError(IntegrationError):
    """Composio refused the request itself (HTTP 4xx other than authentication and not
    found), for example a toolkit it cannot set up."""

    def __init__(self, service: str, message: str, *, http_status: int) -> None:
        super().__init__(service, message)
        self.http_status = http_status


class ComposioClient:
    def __init__(self, http: httpx.AsyncClient, *, api_key: str, base_url: str) -> None:
        self._http = http
        self._api_key = api_key
        self._base_url = base_url

    # --- Connected accounts ------------------------------------------------------------

    async def list_active_accounts(self, user_id: str) -> list[ComposioAccount]:
        document = await self._request(
            "GET",
            "/connected_accounts",
            params={"user_ids": user_id, "statuses": _ACTIVE},
        )
        return [
            account
            for item in _list(document.get("items"))
            if (account := parse_account(item)) is not None
        ]

    async def get_account(self, account_id: str) -> ComposioAccount:
        document = await self._request("GET", f"/connected_accounts/{account_id}")
        account = parse_account(document)
        if account is None:
            raise IntegrationError(SERVICE_NAME, "returned a connected account without an id.")
        return account

    async def delete_account(self, account_id: str) -> None:
        await self._request("DELETE", f"/connected_accounts/{account_id}")

    async def find_auth_config(self, toolkit_slug: str) -> str | None:
        """The id of an auth config for the toolkit, when the project has one."""
        document = await self._request(
            "GET", "/auth_configs", params={"toolkit_slug": toolkit_slug}
        )
        for item in _list(document.get("items")):
            config = _object(item)
            toolkit = _object(config.get("toolkit"))
            if _text(toolkit.get("slug"), lower=True) in {toolkit_slug, None}:
                config_id = _text(config.get("id"))
                if config_id is not None:
                    return config_id
        return None

    async def create_managed_auth_config(self, toolkit_slug: str) -> str:
        """Create an auth config for the toolkit that signs users in through Composio's own
        app registration, and return its id. Raises ``ComposioRejectedError`` when Composio
        cannot set one up for the toolkit."""
        document = await self._request(
            "POST",
            "/auth_configs",
            json={
                "toolkit": {"slug": toolkit_slug},
                "auth_config": {"type": "use_composio_managed_auth", "credentials": {}},
            },
        )
        config_id = _text(_object(document.get("auth_config")).get("id"))
        if config_id is None:
            raise IntegrationError(SERVICE_NAME, "created an auth config without an id.")
        return config_id

    async def link_account(
        self, user_id: str, auth_config_id: str, *, callback_url: str | None
    ) -> ComposioLink:
        body: JsonObject = {"auth_config_id": auth_config_id, "user_id": user_id}
        if callback_url is not None:
            body["callback_url"] = callback_url
        document = await self._request("POST", "/connected_accounts/link", json=body)
        redirect_url = _first_text(document, "redirect_url", "redirectUrl", "url", "link_url")
        request_id = _first_text(document, "id", "link_token", "connected_account_id")
        if redirect_url is None or request_id is None:
            raise IntegrationError(SERVICE_NAME, "returned a connect link without an address.")
        return ComposioLink(
            request_id=request_id,
            redirect_url=redirect_url,
            connected_account_id=_first_text(
                document, "connected_account_id", "connectedAccountId"
            ),
        )

    # --- Tool Router -------------------------------------------------------------------

    async def create_session(
        self, user_id: str, toolkit_slug: str, account_ids: Sequence[str]
    ) -> str:
        body: JsonObject = {
            "user_id": user_id,
            "toolkits": {"enable": [toolkit_slug]},
            "multi_account": {
                "enable": True,
                "max_accounts_per_toolkit": _MAX_ACCOUNTS_PER_TOOLKIT,
                "require_explicit_selection": False,
            },
            "manage_connections": {"enable": False},
        }
        if account_ids:
            body["connected_accounts"] = {toolkit_slug: list(account_ids)}
        document = await self._request("POST", "/tool_router/session", json=body)
        session_id = _first_text(document, "session_id", "id")
        if session_id is None:
            raise IntegrationError(SERVICE_NAME, "returned a tool session without an id.")
        return session_id

    async def search_tools(
        self, session_id: str, use_case: str, *, known_fields: Mapping[str, object] | None = None
    ) -> list[ComposioToolMatch]:
        query: JsonObject = {"use_case": use_case[:_MAX_USE_CASE_CHARS]}
        if known_fields:
            query["known_fields"] = ", ".join(
                f"{key}:{value}" for key, value in known_fields.items()
            )[:_MAX_KNOWN_FIELDS_CHARS]
        document = await self._request(
            "POST", f"/tool_router/session/{session_id}/search", json={"queries": [query]}
        )
        return parse_tool_matches(document)

    async def execute_tool(
        self, session_id: str, tool_slug: str, arguments: Mapping[str, object]
    ) -> ComposioExecution:
        document = await self._request(
            "POST",
            f"/tool_router/session/{session_id}/execute",
            json={"tool_slug": tool_slug, "arguments": dict(arguments)},
        )
        error = _text(document.get("error"))
        successful = document.get("successful")
        return ComposioExecution(
            successful=bool(successful) if isinstance(successful, bool) else error is None,
            data=document.get("data"),
            error=error,
        )

    # --- Transport ---------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: JsonObject | None = None,
    ) -> JsonObject:
        try:
            response = await self._http.request(
                method,
                f"{self._base_url}{_API}{path}",
                params=params,
                json=json,
                headers={"x-api-key": self._api_key, "Accept": "application/json"},
            )
        except httpx.TimeoutException as error:
            raise IntegrationError(SERVICE_NAME, "the request timed out.") from error
        except httpx.HTTPError as error:
            raise IntegrationError(SERVICE_NAME, "could not be reached.") from error

        status = response.status_code
        if status == 404:
            raise ComposioNotFoundError(SERVICE_NAME, "the requested record does not exist.")
        if status in (401, 403):
            raise IntegrationError(
                SERVICE_NAME,
                f"rejected the API key (HTTP {status}). Check that COMPOSIO_API_KEY is a "
                "project key with access to connected accounts and tool sessions.",
            )
        if status >= 400:
            logger.warning("composio_request_failed", path=path, http_status=status)
            if status < 500:
                raise ComposioRejectedError(
                    SERVICE_NAME, f"rejected the request (HTTP {status}).", http_status=status
                )
            raise IntegrationError(SERVICE_NAME, f"rejected the request (HTTP {status}).")
        if not response.content:
            return {}
        try:
            document = response.json()
        except ValueError as error:
            raise IntegrationError(
                SERVICE_NAME, "answered with something that is not JSON."
            ) from error
        return document if isinstance(document, dict) else {"items": document}


# --- Parsing ---------------------------------------------------------------------------


def parse_account(value: object) -> ComposioAccount | None:
    account = _object(value)
    account_id = _text(account.get("id"))
    if account_id is None:
        return None
    toolkit = _object(account.get("toolkit"))
    auth_config = _object(account.get("auth_config") or account.get("authConfig"))
    email = _account_email(account)
    return ComposioAccount(
        id=account_id,
        status=(_text(account.get("status")) or "").upper(),
        toolkit_slug=(
            _text(toolkit.get("slug"), lower=True)
            or _text(account.get("toolkit_slug"), lower=True)
            or _text(auth_config.get("toolkit_slug"), lower=True)
        ),
        auth_config_id=_text(auth_config.get("id")),
        label=_first_text(account, "label", "alias", "word_id") or email,
        email=email,
    )


def parse_tool_matches(document: Mapping[str, Any]) -> list[ComposioToolMatch]:
    schemas = _object(document.get("tool_schemas") or document.get("toolSchemas"))
    slugs: list[str] = []
    for result in _list(document.get("results")):
        record = _object(result)
        for slug in _list(record.get("primary_tool_slugs") or record.get("primaryToolSlugs")):
            text = _text(slug)
            if text is not None and text not in slugs:
                slugs.append(text)
    slugs.extend(slug for slug in schemas if slug not in slugs)

    matches = []
    for slug in slugs:
        schema = _object(schemas.get(slug))
        parameters = schema.get("input_parameters") or schema.get("inputParameters")
        matches.append(
            ComposioToolMatch(
                slug=slug,
                description=_text(schema.get("description")),
                input_schema=parameters if isinstance(parameters, dict) else None,
            )
        )
    return matches


def _account_email(account: Mapping[str, Any]) -> str | None:
    for container in (account, _object(account.get("params")), _object(account.get("data"))):
        value = _first_text(container, "user_email", "userEmail", "email")
        if value is not None:
            return value
    return None


def _object(value: object) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _text(value: object, *, lower: bool = False) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    return text.lower() if lower else text


def _first_text(record: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _text(record.get(key))
        if value is not None:
            return value
    return None
