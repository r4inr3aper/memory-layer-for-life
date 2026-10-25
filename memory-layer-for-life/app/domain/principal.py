"""The signed-in user a request acts for."""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    """A user proven by a verified Supabase access token.

    ``id`` is the Supabase user id. ``email`` and ``display_name`` come from the token's
    claims and can be absent, for example for a phone sign-in.
    """

    id: uuid.UUID
    email: str | None = None
    display_name: str | None = None
