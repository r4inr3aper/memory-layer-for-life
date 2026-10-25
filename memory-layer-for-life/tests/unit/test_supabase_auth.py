"""Verification of Supabase access tokens against a locally generated signing key."""

import json
import time
import uuid
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.domain.errors import AuthenticationRequiredError, IntegrationError
from app.integrations.supabase_auth import (
    SupabaseTokenVerifier,
    http_jwks_fetcher,
    principal_from_claims,
)

ISSUER = "https://project.supabase.co/auth/v1"
AUDIENCE = "authenticated"


class SigningKey:
    def __init__(self, kid: str) -> None:
        self.kid = kid
        self.private = ec.generate_private_key(ec.SECP256R1())

    def jwk(self) -> dict[str, Any]:
        public: dict[str, Any] = json.loads(
            jwt.algorithms.ECAlgorithm.to_jwk(self.private.public_key())
        )
        return {**public, "kid": self.kid, "alg": "ES256", "use": "sig"}

    def sign(self, **overrides: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": str(USER_ID),
            "aud": AUDIENCE,
            "iss": ISSUER,
            "iat": now,
            "exp": now + 3600,
            "role": "authenticated",
            "email": "ada@example.com",
            "user_metadata": {"full_name": "Ada Lovelace"},
        }
        claims.update(overrides)
        claims = {key: value for key, value in claims.items() if value is not None}
        return jwt.encode(claims, self.private, algorithm="ES256", headers={"kid": self.kid})


USER_ID = uuid.uuid4()


class KeySet:
    """Serves a JWKS document and counts how often it was fetched."""

    def __init__(self, *keys: SigningKey) -> None:
        self.keys = list(keys)
        self.fetches = 0

    async def __call__(self) -> dict[str, Any]:
        self.fetches += 1
        return {"keys": [key.jwk() for key in self.keys]}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def verifier(keys: KeySet, clock: Clock | None = None) -> SupabaseTokenVerifier:
    return SupabaseTokenVerifier(
        keys,
        issuer=ISSUER,
        audience=AUDIENCE,
        cache_seconds=600,
        monotonic=clock or Clock(),
    )


async def test_a_valid_token_yields_the_user() -> None:
    key = SigningKey("k1")

    principal = await verifier(KeySet(key)).verify(key.sign())

    assert principal.id == USER_ID
    assert principal.email == "ada@example.com"
    assert principal.display_name == "Ada Lovelace"


async def test_keys_are_fetched_once_and_cached() -> None:
    key = SigningKey("k1")
    keys = KeySet(key)
    check = verifier(keys)

    await check.verify(key.sign())
    await check.verify(key.sign())

    assert keys.fetches == 1


async def test_a_rotated_key_is_picked_up_with_one_refresh() -> None:
    old, new = SigningKey("old"), SigningKey("new")
    keys = KeySet(old)
    clock = Clock()
    check = verifier(keys, clock)
    await check.verify(old.sign())

    keys.keys = [new]
    clock.now += 60
    principal = await check.verify(new.sign())

    assert principal.id == USER_ID
    assert keys.fetches == 2


async def test_unknown_key_ids_cannot_make_the_api_refetch_constantly() -> None:
    known, forged = SigningKey("known"), SigningKey("forged")
    keys = KeySet(known)
    check = verifier(keys, Clock())
    await check.verify(known.sign())

    for _ in range(5):
        with pytest.raises(AuthenticationRequiredError):
            await check.verify(forged.sign())

    assert keys.fetches == 1


async def test_an_expired_token_asks_the_user_to_sign_in_again() -> None:
    key = SigningKey("k1")
    past = int(time.time()) - 7200

    with pytest.raises(AuthenticationRequiredError, match="expired"):
        await verifier(KeySet(key)).verify(key.sign(iat=past, exp=past + 60))


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://other.supabase.co/auth/v1"},
        {"aud": "something-else"},
        {"role": "anon"},
        {"role": "service_role"},
        {"sub": "not-a-uuid"},
        {"sub": None},
        {"exp": None},
    ],
    ids=["issuer", "audience", "anon", "service_role", "subject", "no_subject", "no_expiry"],
)
async def test_tokens_that_are_not_a_user_s_are_rejected(overrides: dict[str, Any]) -> None:
    key = SigningKey("k1")

    with pytest.raises(AuthenticationRequiredError):
        await verifier(KeySet(key)).verify(key.sign(**overrides))


async def test_a_token_signed_by_another_key_with_the_same_id_is_rejected() -> None:
    real, impostor = SigningKey("k1"), SigningKey("k1")

    with pytest.raises(AuthenticationRequiredError):
        await verifier(KeySet(real)).verify(impostor.sign())


async def test_shared_secret_tokens_are_never_accepted() -> None:
    token = jwt.encode(
        {"sub": str(USER_ID), "aud": AUDIENCE, "iss": ISSUER, "role": "authenticated"},
        "a-shared-secret-of-sufficient-length-1234567890",
        algorithm="HS256",
        headers={"kid": "k1"},
    )

    with pytest.raises(AuthenticationRequiredError):
        await verifier(KeySet(SigningKey("k1"))).verify(token)


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c"])
async def test_malformed_tokens_are_rejected(token: str) -> None:
    with pytest.raises(AuthenticationRequiredError):
        await verifier(KeySet(SigningKey("k1"))).verify(token)


def test_missing_profile_claims_are_absent_not_invented() -> None:
    principal = principal_from_claims({"sub": str(USER_ID), "role": "authenticated"})

    assert principal.email is None
    assert principal.display_name is None


# --- Fetching the key set over HTTP ----------------------------------------------------


def jwks_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_the_key_set_is_fetched_from_the_project() -> None:

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"keys": [SigningKey("k1").jwk()]})

    fetch = http_jwks_fetcher(
        jwks_client(handler), "https://p.supabase.co/auth/v1/.well-known/jwks.json"
    )
    document = await fetch()

    assert seen == ["https://p.supabase.co/auth/v1/.well-known/jwks.json"]
    assert document["keys"][0]["kid"] == "k1"


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"status": 503, "text": "down"}, "HTTP 503"),
        ({"status": 200, "text": "<html>"}, "not valid JSON"),
        ({"status": 200, "text": "[1, 2]"}, "not a key set"),
    ],
    ids=["unavailable", "not_json", "not_a_set"],
)
async def test_an_unusable_key_set_is_an_integration_error(
    response: dict[str, Any], expected: str
) -> None:

    fetch = http_jwks_fetcher(
        jwks_client(lambda request: httpx.Response(response["status"], text=response["text"])),
        "https://p.supabase.co/jwks",
    )

    with pytest.raises(IntegrationError, match=expected):
        await fetch()


async def test_an_unreachable_key_set_is_an_integration_error() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(IntegrationError, match="could not be fetched"):
        await http_jwks_fetcher(jwks_client(handler), "https://p.supabase.co/jwks")()


async def test_keys_this_build_cannot_use_are_skipped() -> None:
    usable = SigningKey("good")
    keys = KeySet(usable)
    original = keys.__call__

    async def with_a_broken_key() -> dict[str, Any]:
        document = await original()
        document["keys"].append({"kid": "broken", "kty": "EC", "crv": "P-999", "x": "a", "y": "b"})
        document["keys"].append("not-a-key")
        return document

    check = SupabaseTokenVerifier(
        with_a_broken_key, issuer=ISSUER, audience=AUDIENCE, cache_seconds=600, monotonic=Clock()
    )

    assert (await check.verify(usable.sign())).id == USER_ID
