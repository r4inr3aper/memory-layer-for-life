"""Chats become memories (ADR-037, ADR-048).

A chat is captured once it has been quiet for ``quiet_after``: what the user wrote since
the last capture becomes one unit of their evidence, which the memory pipeline reads as a
conversation with the assistant, in one model call.

* Only the user's own words are evidence, never the assistant's replies: memories are
  about the user, and a reply restating a guess must not become a "fact". The assistant
  message each line answered travels with it as context, in the evidence's metadata, so a
  replay reads exactly what the first run read. So does a list of what the assistant
  saved itself during the conversation (a reminder), which the extractor then skips.
* A stretch of chat with nothing that can carry a memory (greetings, thanks, approvals, a
  message sent again) costs no model call (``app.domain.conversation``): the capture
  watermark simply moves past it.
* Reading a whole quiet stretch at once gives the extractor what a single message lacks
  ("yes", "the second one", a correction two lines later), and repeats within it become
  one memory.
* Capture never affects the chat. It runs in the pipeline loop (``PipelineLoop``), which
  also processes what it captures. Two processes capturing the same chat build the same
  unit, and ingestion's identities make the second a no-op.
* Users can turn it off for themselves (``memory_capture_enabled``), the operator for
  everyone (``MEMORY_CAPTURE_ENABLED``). Messages sent while it is off are passed over,
  never captured later.

The extractor also names the conversation: ``ChatTitleHook`` gives a side chat that name
once, in the transaction that stores the unit's results.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.session import transaction
from app.domain.conversation import (
    Admission,
    CapturedLine,
    ChatLine,
    admission,
    conversation_title,
    plan_segment,
    repeat_key,
)
from app.domain.enums import ChatRole, MessageSource
from app.domain.errors import DomainError
from app.domain.memory_policy import display_title
from app.models.chat_message import ChatMessage
from app.models.raw_message import RawMessage
from app.repositories.chat_repository import ChatRepository, ThreadToCapture
from app.repositories.memory_repository import MemoryRepository
from app.repositories.message_repository import MessageRepository
from app.schemas.extraction import ExtractionOutput
from app.schemas.message_metadata import MessageMetadata
from app.schemas.raw_message import RawMessageCreate
from app.services.ingestion import IngestionService
from app.services.processing.extraction import (
    ALREADY_SAVED_KEY,
    ASSISTANT_BEFORE_KEY,
    UNIT_TIMEZONE_KEY,
)
from app.services.queries import chat_thread_id

logger = structlog.get_logger(__name__)

# Messages read from one chat per pass; a longer backlog is read over several passes.
_SCAN_LIMIT: Final = 200
# A line the user already sent within this window is a resend, not something new.
_REPEAT_WINDOW: Final = timedelta(hours=24)
# What the assistant saved shortly before a segment's first line belongs to it too.
_SAVED_LOOKBACK: Final = timedelta(minutes=2)


def worth_capturing(text: str) -> bool:
    """Whether a message can carry a memory on its own (``app.domain.conversation``)."""
    return admission(text) is Admission.CAPTURE


class MemoryCapture:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        ingestion: IngestionService,
        enabled: bool,
        quiet_after: timedelta,
        max_unit_messages: int,
        default_timezone: str,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._ingestion = ingestion
        self._enabled = enabled
        self._quiet_after = quiet_after
        self._max_unit_messages = max_unit_messages
        self._default_timezone = default_timezone
        self._clock = clock

    async def next_due(self) -> datetime | None:
        """When the chat that has waited longest becomes quiet enough to capture."""
        if not self._enabled:
            return None
        async with self._session_factory() as session:
            activity = await ChatRepository(session).next_capture_activity()
        return activity + self._quiet_after if activity is not None else None

    async def capture_quiet_chats(self, *, limit: int) -> int:
        """Capture up to ``limit`` chats that went quiet. Returns the units queued; the
        pipeline processes them in the same pass. A chat that fails is tried again on the
        next pass: its watermark did not move."""
        if not self._enabled:
            return 0
        now = self._clock()
        async with self._session_factory() as session:
            threads = await ChatRepository(session).threads_to_capture(
                quiet_before=now - self._quiet_after, limit=limit
            )
        units = 0
        for thread in threads:
            try:
                units += await self._capture_thread(thread, now)
            except DomainError as error:
                logger.warning(
                    "memory_capture_failed", thread_id=str(thread.id), error_code=error.code
                )
            except Exception:
                logger.exception("memory_capture_crashed", thread_id=str(thread.id))
        return units

    async def _capture_thread(self, thread: ThreadToCapture, now: datetime) -> int:
        async with self._session_factory() as session:
            chat = ChatRepository(session)
            messages = await chat.messages_after(
                thread.id, after=thread.captured_through, limit=_SCAN_LIMIT
            )
            if not messages or not thread.capture_enabled:
                # Activity without new messages (a cleared chat), or capture turned off.
                through = messages[-1].created_at if messages else thread.updated_at
                await self._mark(thread.id, through)
                return 0
            previous = await chat.last_assistant_text(thread.id, before=messages[0].created_at)
            recent = await MessageRepository(session).recent_contents(
                thread.user_id, source=MessageSource.APP_CHAT.value, since=now - _REPEAT_WINDOW
            )

        plan = plan_segment(
            [_chat_line(message) for message in messages],
            previous_assistant=previous,
            said_recently={repeat_key(text) for text in recent},
            max_user_lines=self._max_unit_messages,
        )
        through = plan.through or messages[-1].created_at
        if not plan.worth_extracting:
            await self._mark(thread.id, through)
            return 0

        first_line = plan.lines[0].line
        async with self._session_factory() as session:
            saved = await MemoryRepository(session).saved_by_assistant_since(
                thread.user_id, first_line.created_at - _SAVED_LOOKBACK
            )
        timezone_name = thread.timezone or self._default_timezone
        already_saved = [display_title(memory.content, memory.metadata_) for memory in saved]
        await self._ingestion.ingest(
            [
                [
                    _evidence(
                        captured,
                        thread_id=thread.id,
                        timezone_name=timezone_name,
                        already_saved=already_saved if index == 0 else (),
                    )
                    for index, captured in enumerate(plan.lines)
                ]
            ],
            owner_id=thread.user_id,
        )
        await self._mark(thread.id, through)
        return 1

    async def _mark(self, thread_id: uuid.UUID, through: datetime) -> None:
        async with transaction(self._session_factory) as session:
            await ChatRepository(session).mark_captured(thread_id, through)


class ChatTitleHook:
    """Names a side chat from the conversation the extractor read, once (ADR-048). Runs in
    the transaction that stores the unit's results (``MaterializeHook``)."""

    async def __call__(
        self,
        session: AsyncSession,
        output: ExtractionOutput,
        messages: Sequence[RawMessage],
    ) -> None:
        title = conversation_title(output.conversation_title)
        if title is None:
            return
        threads = {
            thread_id
            for message in messages
            if message.source == MessageSource.APP_CHAT.value
            and (thread_id := chat_thread_id(message)) is not None
        }
        chat = ChatRepository(session)
        for thread_id in sorted(threads, key=str):
            await chat.name_thread(thread_id, title)


def _chat_line(message: ChatMessage) -> ChatLine:
    role = ChatRole(message.role)
    text = message.content
    if role is ChatRole.USER and MessageMetadata.from_json(message.metadata_).attachments:
        # A message of only files is stored as "Attached: <names>"; it has no words.
        text = "" if message.content.startswith("Attached: ") else message.content
    return ChatLine(id=message.id, role=role, text=text, created_at=message.created_at)


def _evidence(
    captured: CapturedLine,
    *,
    thread_id: uuid.UUID,
    timezone_name: str,
    already_saved: Sequence[str],
) -> RawMessageCreate:
    metadata: dict[str, Any] = {
        "thread_id": str(thread_id),
        UNIT_TIMEZONE_KEY: timezone_name,
        "admission": captured.admission.value,
    }
    if captured.assistant_before is not None:
        metadata[ASSISTANT_BEFORE_KEY] = captured.assistant_before
    if already_saved:
        metadata[ALREADY_SAVED_KEY] = list(already_saved)
    return RawMessageCreate(
        source=MessageSource.APP_CHAT,
        content=captured.line.text,
        # The chat message's id makes capture idempotent.
        source_message_id=str(captured.line.id),
        source_created_at=captured.line.created_at,
        metadata=metadata,
    )
