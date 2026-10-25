"""Reminders and daily briefs, sent by the API itself.

Every pass:

1. Reminders whose time has come are claimed (row locks skip what another process holds),
   cleared, recorded in their memory's history, and posted to the user's main chat with
   a card offering Done and Snooze. A push follows, unless the user turned reminders or
   notifications off. A sensitive memory's text stays out of chat and the notification.
2. For each user with the brief on, whose local brief time has come today and not more
   than ``BRIEF_GRACE`` ago, the day is claimed in the database, so the brief goes once,
   whatever the number of processes. It is posted to the main chat (with the items it asks
   about) and pushed, unless their quiet hours hold. A day with nothing to say is claimed
   and skipped.

Posting happens in the claiming transaction, so a crash never loses a claimed reminder
silently. The push is sent after the commit and may be lost; the chat message is not.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.session import transaction
from app.domain.enums import ChatRole, MemoryEventAction, Sensitivity
from app.domain.life_state import brief_due, in_quiet_hours, next_brief_at
from app.models.app_user import AppUser
from app.models.memory import Memory
from app.repositories.chat_repository import ChatRepository
from app.repositories.life_repository import LifeRepository
from app.repositories.memory_repository import MemoryRepository
from app.repositories.user_repository import UserRepository
from app.schemas.message_metadata import BriefItemNote, BriefNote, MessageMetadata, ReminderNote
from app.services.chat import MAIN_THREAD_TITLE, append_message
from app.services.life_state import compose_user_brief, user_timezone
from app.services.notifications import PushNotice, PushService
from app.services.pacing import ALWAYS_ON, BackgroundPacer

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE: Final = 50
PRIVATE_REMINDER: Final = "You set a reminder on a private memory. Open Memories to see it."


@dataclass(frozen=True, slots=True)
class ProactiveReport:
    reminders: int = 0
    briefs: int = 0


class ProactiveDispatcher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        push: PushService,
        *,
        default_timezone: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._push = push
        self._default_timezone = default_timezone
        self._batch_size = batch_size
        self._clock = clock

    async def next_due(self) -> datetime | None:
        """When the next reminder or daily brief falls due."""
        now = self._clock()
        async with self._session_factory() as session:
            life = LifeRepository(session)
            reminder = await life.next_reminder_at()
            candidates = [reminder] if reminder is not None else []
            for user in await life.brief_users():
                local_now = now.astimezone(user_timezone(user, self._default_timezone))
                candidates.append(next_brief_at(local_now, user.brief_time, user.last_brief_on))
        return min(candidates, default=None)

    async def run_due(self) -> ProactiveReport:
        reminders = await self.send_due_reminders()
        briefs = await self.send_due_briefs()
        if reminders or briefs:
            logger.info("proactive_pass", reminders=reminders, briefs=briefs)
        return ProactiveReport(reminders=reminders, briefs=briefs)

    async def send_due_reminders(self) -> int:
        sent = 0
        while True:
            notices: list[PushNotice] = []
            async with transaction(self._session_factory) as session:
                now = self._clock()
                due = await LifeRepository(session).lock_due_reminders(now, limit=self._batch_size)
                for memory in due:
                    notices.append(await self._post_reminder(session, memory, now))
            for notice in notices:
                await self._push.notify(notice)
            sent += len(due)
            if len(due) < self._batch_size:
                return sent

    async def send_due_briefs(self) -> int:
        async with self._session_factory() as session:
            users = await LifeRepository(session).brief_users()
        sent = 0
        for user in users:
            try:
                if await self._send_brief(user.id):
                    sent += 1
            except Exception:
                # One user's failure must not stop everyone else's brief.
                logger.exception("brief_failed", user_id=str(user.id))
        return sent

    async def _post_reminder(
        self, session: AsyncSession, memory: Memory, now: datetime
    ) -> PushNotice:
        assert memory.owner_id is not None  # lock_due_reminders selects owned memories
        sensitive = memory.metadata_.get("sensitivity") == Sensitivity.SENSITIVE.value
        due = memory.remind_at
        memory.remind_at = None
        await MemoryRepository(session).add_event(
            memory.id,
            MemoryEventAction.REMINDED,
            now=now,
            details={"due": due.isoformat() if due else None},
        )
        chat = ChatRepository(session)
        thread = await chat.ensure_main_thread(memory.owner_id, title=MAIN_THREAD_TITLE, now=now)
        text = PRIVATE_REMINDER if sensitive else memory.content
        message = await append_message(
            chat,
            thread,
            role=ChatRole.ASSISTANT,
            content=f"Reminder: {text}",
            metadata=MessageMetadata(
                reminder=ReminderNote(memory_id=memory.id, sensitive=sensitive)
            ),
            now=now,
        )
        return PushNotice(
            user_id=memory.owner_id,
            title="Reminder",
            body="A private reminder" if sensitive else memory.content,
            data={
                "thread_id": str(thread.id),
                "message_id": str(message.id),
                "memory_id": str(memory.id),
            },
            is_reminder=True,
        )

    async def _send_brief(self, user_id: uuid.UUID) -> bool:
        notice: PushNotice | None = None
        async with transaction(self._session_factory) as session:
            user = await UserRepository(session).get(user_id)
            if user is None or not user.brief_enabled:
                return False
            now = self._clock()
            local_now = now.astimezone(user_timezone(user, self._default_timezone))
            if not brief_due(local_now, user.brief_time, user.last_brief_on):
                return False
            if not await LifeRepository(session).claim_brief(user.id, local_now.date()):
                return False
            brief = await compose_user_brief(session, user, now, self._default_timezone)
            if brief.nothing_to_say:
                return False
            chat = ChatRepository(session)
            thread = await chat.ensure_main_thread(user.id, title=MAIN_THREAD_TITLE, now=now)
            follow_ups = [
                BriefItemNote(memory_id=item.memory_id, content=item.content)
                for item in brief.follow_ups
            ]
            message = await append_message(
                chat,
                thread,
                role=ChatRole.ASSISTANT,
                content=brief.text,
                metadata=MessageMetadata(
                    brief=BriefNote(day=local_now.date(), follow_ups=follow_ups)
                ),
                now=now,
            )
            if not _quiet(user, local_now):
                notice = PushNotice(
                    user_id=user.id,
                    title="Your day",
                    body=brief.summary,
                    data={"thread_id": str(thread.id), "message_id": str(message.id)},
                )
        if notice is not None:
            await self._push.notify(notice)
        return True


def _quiet(user: AppUser, local_now: datetime) -> bool:
    return in_quiet_hours(local_now.time(), user.quiet_hours_start, user.quiet_hours_end)


class ProactiveLoop:
    """Runs a pass every ``interval_seconds`` while the API runs, or as the pacer allows
    when the database should sleep (``app.services.pacing``)."""

    def __init__(
        self,
        dispatcher: ProactiveDispatcher,
        *,
        interval_seconds: float,
        pacer: BackgroundPacer = ALWAYS_ON,
    ) -> None:
        self._dispatcher = dispatcher
        self._interval_seconds = interval_seconds
        self._pacer = pacer
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="proactive-loop")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self._dispatcher.run_due()
            except Exception:
                # A failed pass must not end the loop; the next pass tries again.
                logger.exception("proactive_pass_failed")
            next_due = await self._pacer.next_due(self._dispatcher.next_due, loop="proactive")
            await self._pacer.sleep(self._interval_seconds, next_due=next_due)
