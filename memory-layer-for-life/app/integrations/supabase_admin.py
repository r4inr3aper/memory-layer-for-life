"""Supabase Auth's admin API, used for one thing: deleting a user's sign-in identity when
they delete their account.

It needs the project's secret key, which can act on every user, so nothing else in the
application uses it. With the newer ``sb_secret_...`` keys the key goes in the ``apikey``
header only; Supabase's gateway turns it into a short-lived token itself.
"""

import uuid
from typing import Final

import httpx

from app.domain.errors import IntegrationError

SERVICE_NAME: Final = "Supabase Auth"


class SupabaseAdminClient:
    def __init__(self, http: httpx.AsyncClient, *, supabase_url: str, secret_key: str) -> None:
        self._http = http
        self._url = supabase_url
        self._secret_key = secret_key

    async def delete_user(self, user_id: uuid.UUID) -> None:
        """Delete the identity. One that is already gone counts as deleted."""
        try:
            response = await self._http.delete(
                f"{self._url}/auth/v1/admin/users/{user_id}",
                headers={"apikey": self._secret_key, "Accept": "application/json"},
            )
        except httpx.HTTPError as error:
            raise IntegrationError(SERVICE_NAME, "could not be reached.") from error
        if response.status_code == 404:
            return
        if response.status_code in (401, 403):
            raise IntegrationError(SERVICE_NAME, "rejected SUPABASE_SECRET_KEY.")
        if response.status_code >= 400:
            raise IntegrationError(
                SERVICE_NAME, f"could not delete the user (HTTP {response.status_code})."
            )
