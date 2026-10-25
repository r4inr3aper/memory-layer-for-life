"""Push notifications to the user's devices.

The app registers each device's Expo push token. A user is notified on every device when
a scheduled run finishes, when a reminder they set is due, and when their daily brief is
ready, unless they turned notifications off. Reminders also follow their own switch; the
brief stays silent during quiet hours (the caller decides, knowing the user's local
time). A failed notification never affects what triggered it: it is logged and dropped.
Tokens Expo reports as dead are deleted.
"""

import uuid
from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.session import transaction
from app.domain.enums import DevicePlatform
from app.domain.errors import DomainError
from app.domain.principal import Principal
from app.integrations.expo_push import ExpoPushClient, PushMessage
from app.repositories.push_token_repository import PushTokenRepository
from app.repositories.user_repository import UserRepository

logger = structlog.get_logger(__name__)

_MAX_BODY_CHARS: Final = 180


@dataclass(frozen=True, slots=True)
class RunNotice:
    """What a notification about a finished scheduled run says, and where it leads."""

    user_id: uuid.UUID
    scheduled_task_id: uuid.UUID
    run_id: uuid.UUID
    title: str
    succeeded: bool
    text: str | None
    thread_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class PushNotice:
    user_id: uuid.UUID
    title: str
    body: str
    data: dict[str, str]
    # Sent only while the user keeps reminders on.
    is_reminder: bool = False


class PushService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: ExpoPushClient | None,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._clock = clock

    async def register(self, principal: Principal, token: str, platform: DevicePlatform) -> None:
        async with transaction(self._session_factory) as session:
            await PushTokenRepository(session).register(
                principal.id, token, platform, now=self._clock()
            )

    async def unregister(self, principal: Principal, token: str) -> None:
        async with transaction(self._session_factory) as session:
            await PushTokenRepository(session).unregister(principal.id, token)

    async def notify_run_finished(self, notice: RunNotice) -> None:
        await self.notify(
            PushNotice(
                user_id=notice.user_id,
                title=_title(notice),
                body=_body(notice),
                data=_data(notice),
            )
        )

    async def notify(self, notice: PushNotice) -> None:
        if self._client is None:
            return
        try:
            async with self._session_factory() as session:
                user = await UserRepository(session).get(notice.user_id)
                if user is None or not user.notifications_enabled:
                    return
                if notice.is_reminder and not user.reminders_enabled:
                    return
                tokens = await PushTokenRepository(session).tokens_for(notice.user_id)
            if not tokens:
                return
            receipt = await self._client.send(
                [
                    PushMessage(
                        token=token,
                        title=notice.title,
                        body=shorten(notice.body),
                        data=notice.data,
                    )
                    for token in tokens
                ]
            )
            if receipt.unregistered_tokens:
                async with transaction(self._session_factory) as session:
                    await PushTokenRepository(session).forget(receipt.unregistered_tokens)
        except DomainError as error:
            logger.warning("push_notification_failed", error_code=error.code)
        except Exception:
            logger.exception("push_notification_crashed")


def _title(notice: RunNotice) -> str:
    state = "done" if notice.succeeded else "failed"
    return f"{notice.title}: {state}"


def _body(notice: RunNotice) -> str:
    text = " ".join((notice.text or "").split())
    if not text:
        return "Open Muse to see the result." if notice.succeeded else "Open Muse to see why."
    return text


def shorten(text: str) -> str:
    """One line a lock screen can show."""
    line = " ".join(text.split())
    return line if len(line) <= _MAX_BODY_CHARS else f"{line[: _MAX_BODY_CHARS - 1]}…"


def _data(notice: RunNotice) -> dict[str, str]:
    data = {"scheduled_task_id": str(notice.scheduled_task_id), "run_id": str(notice.run_id)}
    if notice.thread_id is not None:
        data["thread_id"] = str(notice.thread_id)
    return data
