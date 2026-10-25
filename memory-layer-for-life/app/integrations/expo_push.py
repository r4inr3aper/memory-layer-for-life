"""Expo's push service: one HTTP API that delivers to iOS and Android devices.

The app registers an Expo push token per device; the backend sends notifications to those
tokens. Expo answers each message with a ticket, and a ticket whose error is
``DeviceNotRegistered`` means the token is dead and should be forgotten.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import httpx
import structlog

from app.domain.errors import IntegrationError

logger = structlog.get_logger(__name__)

SERVICE_NAME: Final = "Expo push"
PUSH_URL: Final = "https://exp.host/--/api/v2/push/send"
# Expo accepts at most this many messages per request.
_BATCH_SIZE: Final = 100
_UNREGISTERED: Final = "DeviceNotRegistered"


@dataclass(frozen=True, slots=True)
class PushMessage:
    token: str
    title: str
    body: str
    data: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PushReceipt:
    """What Expo said about each message: sent, or the tokens that are no longer valid."""

    sent: int
    unregistered_tokens: tuple[str, ...]


class ExpoPushClient:
    def __init__(self, http: httpx.AsyncClient, *, access_token: str | None) -> None:
        self._http = http
        self._access_token = access_token

    async def send(self, messages: Sequence[PushMessage]) -> PushReceipt:
        sent = 0
        unregistered: list[str] = []
        for start in range(0, len(messages), _BATCH_SIZE):
            batch = messages[start : start + _BATCH_SIZE]
            tickets = await self._post(batch)
            for message, ticket in zip(batch, tickets, strict=False):
                if ticket.get("status") == "ok":
                    sent += 1
                    continue
                details = ticket.get("details")
                error = details.get("error") if isinstance(details, dict) else None
                if error == _UNREGISTERED:
                    unregistered.append(message.token)
                else:
                    logger.warning("push_ticket_failed", error=error)
        return PushReceipt(sent=sent, unregistered_tokens=tuple(unregistered))

    async def _post(self, batch: Sequence[PushMessage]) -> list[dict[str, Any]]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._access_token is not None:
            headers["Authorization"] = f"Bearer {self._access_token}"
        body = [
            {
                "to": message.token,
                "title": message.title,
                "body": message.body,
                "data": dict(message.data),
                "sound": "default",
            }
            for message in batch
        ]
        try:
            response = await self._http.post(PUSH_URL, json=body, headers=headers)
        except httpx.HTTPError as error:
            raise IntegrationError(SERVICE_NAME, "could not be reached.") from error
        if response.status_code >= 400:
            raise IntegrationError(
                SERVICE_NAME, f"rejected the request (HTTP {response.status_code})."
            )
        try:
            tickets = response.json().get("data", [])
        except (ValueError, AttributeError) as error:
            raise IntegrationError(SERVICE_NAME, "answered with an unexpected shape.") from error
        return [ticket for ticket in tickets if isinstance(ticket, dict)]
