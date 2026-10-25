"""Verification of Supabase Auth access tokens.

The app signs users in with Supabase and sends their access token as a bearer token.
This module checks it locally against the project's published signing keys (JWKS), so a
request needs no call to Supabase once the keys are cached.

Only asymmetric algorithms are accepted. A token signed with a shared secret (HS256)
could have been minted by anyone holding that secret, and the API is not given it.

Keys are fetched on first use, never at startup, and cached. A token signed by a key
the cache does not know triggers one refresh, which is how key rotation is picked up;
refreshes are rate limited so that forged key ids cannot make the API hammer Supabase.
"""

import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final, Protocol

import httpx
import jwt
import structlog

from app.domain.errors import AuthenticationRequiredError, IntegrationError
from app.domain.principal import Principal

logger = structlog.get_logger(__name__)

SERVICE_NAME: Final = "Supabase Auth"
ACCEPTED_ALGORITHMS: Final = frozenset({"ES256", "RS256", "EdDSA"})
# Supabase gives every signed-in user this role. Anon and service keys carry others.
_USER_ROLE: Final = "authenticated"
# Tolerated clock difference between Supabase and this server.
_LEEWAY_SECONDS: Final = 30
# A key id the cache does not know triggers at most one refresh in this period.
_MIN_REFRESH_INTERVAL_SECONDS: Final = 30.0
_INVALID_TOKEN: Final = "The access token is not valid. Sign in again."

JwksFetcher = Callable[[], Awaitable[Mapping[str, Any]]]
MonotonicClock = Callable[[], float]


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> Principal: ...


def http_jwks_fetcher(http: httpx.AsyncClient, url: str) -> JwksFetcher:
    """Fetch the key set from Supabase over HTTP."""

    async def fetch() -> Mapping[str, Any]:
        try:
            response = await http.get(url, headers={"Accept": "application/json"})
        except httpx.HTTPError as error:
            raise IntegrationError(
                SERVICE_NAME, "the signing keys could not be fetched."
            ) from error
        if response.status_code != 200:
            raise IntegrationError(
                SERVICE_NAME,
                f"the signing keys could not be fetched (HTTP {response.status_code}).",
            )
        try:
            document = response.json()
        except ValueError as error:
            raise IntegrationError(SERVICE_NAME, "the signing keys are not valid JSON.") from error
        if not isinstance(document, dict):
            raise IntegrationError(SERVICE_NAME, "the signing keys are not a key set.")
        return document

    return fetch


class SupabaseTokenVerifier:
    """``TokenVerifier`` for one Supabase project."""

    def __init__(
        self,
        fetch_jwks: JwksFetcher,
        *,
        issuer: str,
        audience: str,
        cache_seconds: float,
        monotonic: MonotonicClock = time.monotonic,
    ) -> None:
        self._fetch_jwks = fetch_jwks
        self._issuer = issuer
        self._audience = audience
        self._cache_seconds = cache_seconds
        self._monotonic = monotonic
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None

    async def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as error:
            raise AuthenticationRequiredError(_INVALID_TOKEN) from error

        algorithm = header.get("alg")
        key_id = header.get("kid")
        if algorithm not in ACCEPTED_ALGORITHMS or not isinstance(key_id, str):
            raise AuthenticationRequiredError(_INVALID_TOKEN)

        key = await self._key(key_id)
        if key is None:
            raise AuthenticationRequiredError(_INVALID_TOKEN)

        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationRequiredError("The session has expired. Sign in again.") from error
        except jwt.PyJWTError as error:
            raise AuthenticationRequiredError(_INVALID_TOKEN) from error

        return principal_from_claims(claims)

    async def _key(self, key_id: str) -> jwt.PyJWK | None:
        now = self._monotonic()
        expired = self._fetched_at is None or now - self._fetched_at >= self._cache_seconds
        if expired or (
            key_id not in self._keys
            and now - (self._fetched_at or 0) >= (_MIN_REFRESH_INTERVAL_SECONDS)
        ):
            await self._refresh(now)
        return self._keys.get(key_id)

    async def _refresh(self, now: float) -> None:
        document = await self._fetch_jwks()
        keys: dict[str, jwt.PyJWK] = {}
        for entry in document.get("keys", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("kid"), str):
                continue
            try:
                keys[entry["kid"]] = jwt.PyJWK(entry)
            except jwt.PyJWTError:
                # An unusable key, such as one of an algorithm this build cannot verify.
                logger.warning("supabase_jwk_skipped", kid=entry.get("kid"))
        self._keys = keys
        self._fetched_at = now
        logger.info("supabase_jwks_refreshed", key_count=len(keys))


def principal_from_claims(claims: Mapping[str, Any]) -> Principal:
    """Build the principal from verified claims, refusing tokens that are not a user's."""
    if claims.get("role") != _USER_ROLE:
        raise AuthenticationRequiredError(_INVALID_TOKEN)
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError) as error:
        raise AuthenticationRequiredError(_INVALID_TOKEN) from error

    email = claims.get("email")
    metadata = claims.get("user_metadata")
    name: object = None
    if isinstance(metadata, Mapping):
        name = metadata.get("full_name") or metadata.get("name")
    return Principal(
        id=user_id,
        email=email.strip() or None if isinstance(email, str) else None,
        display_name=name.strip()[:200] or None if isinstance(name, str) else None,
    )
