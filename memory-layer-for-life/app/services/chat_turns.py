"""Assistant turns: a user message in, a streamed reply out.

``start`` checks the request and stores the user's message before anything streams, so
a request that cannot be served fails with an ordinary error response. The turn itself
runs as background work and reports through a queue the response reads from. If the
client disconnects, the turn still finishes and its reply is saved; the user sees it
when the thread is reloaded.

One turn runs per thread at a time, across every process serving the API: the thread
holds a lease (``chat_threads.turn_lease_until``) while its reply runs. The lease is
released before the final event is sent, so the app can send its next message at once;
a lease left behind by a process that died expires on its own.
"""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.session import transaction
from app.domain.attachments import ATTACHMENT_TYPES
from app.domain.enums import ChatRole, LlmCallOrigin, LlmOperation, ThreadKind, ToolConnectionStatus
from app.domain.errors import (
    ChatTurnInProgressError,
    DomainError,
    InvalidAttachmentError,
    InvalidChatMessageError,
    ProviderNotConfiguredError,
)
from app.domain.principal import Principal
from app.domain.tool_catalog import find_tool
from app.integrations.assistant.base import AssistantModel, AssistantText, Attachment, UserText
from app.integrations.llm_calls import LlmCallContext
from app.models.chat_message import ChatMessage
from app.repositories.chat_repository import ChatRepository
from app.repositories.tool_connection_repository import ToolConnectionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.message_metadata import AttachmentNote, MessageMetadata
from app.services.assistant.agent import AssistantAgent
from app.services.assistant.context import (
    ProgressEvent,
    TurnContext,
    TurnEvent,
    TurnFailed,
    TurnFinished,
    TurnStarted,
)
from app.services.assistant.prompts import chat_context, chat_instructions
from app.services.assistant.tools import AssistantToolbox
from app.services.background import BackgroundWork
from app.services.chat import (
    NEW_SIDE_THREAD_TITLE,
    append_message,
    existing_thread,
    title_from_text,
    turn_running,
)
from app.services.memory_capture import MemoryCapture
from app.services.usage import UsageService

logger = structlog.get_logger(__name__)

UNEXPECTED_ERROR_CODE: Final = "UNEXPECTED_ERROR"
_UNEXPECTED_ERROR_MESSAGE: Final = "Cooper ran into an unexpected problem. Try again."
_PROPOSAL_FALLBACK: Final = "Schedule this task?"
_EMPTY_REPLY_FALLBACK: Final = "Done."
_APPROVAL_PREFIXES: Final = (
    "yes",
    "yep",
    "yeah",
    "ok",
    "okay",
    "confirm",
    "approved",
    "proceed",
    "go ahead",
    "do it",
    "send it",
    "create it",
)
_APPROVAL_BLOCKERS: Final = ("?", " not ", " don't", " dont", " stop", " cancel")


@dataclass(frozen=True, slots=True)
class TurnLimits:
    max_message_chars: int
    history_messages: int
    max_attachments: int = 3
    max_attachment_bytes: int = 5 * 1024 * 1024
    lease: timedelta = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class _Context:
    history: list[UserText | AssistantText]
    connected_apps: list[str]
    assistant_name: str | None


class ChatTurnService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        model: AssistantModel | None,
        toolbox: AssistantToolbox,
        background: BackgroundWork,
        usage: UsageService,
        max_steps: int,
        limits: TurnLimits,
        capture: MemoryCapture | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._capture = capture
        self._agent = AssistantAgent(model, max_steps=max_steps) if model is not None else None
        self._toolbox = toolbox
        self._background = background
        self._usage = usage
        self._limits = limits
        self._clock = clock

    @property
    def available(self) -> bool:
        return self._agent is not None

    async def start(
        self,
        principal: Principal,
        thread_id: uuid.UUID,
        content: str,
        *,
        timezone_name: str,
        attachments: Sequence[Attachment] = (),
    ) -> AsyncIterator[TurnEvent]:
        """Store the user's message, start the turn, and return its event stream.

        Raises before anything is stored when the message or its files are invalid, no
        model is configured, the thread does not exist, a reply is already running in it,
        or the user is over a usage limit.
        """
        text = content.strip()
        self._check_attachments(attachments)
        if not text and not attachments:
            raise InvalidChatMessageError("A message must contain something other than spaces.")
        if len(text) > self._limits.max_message_chars:
            raise InvalidChatMessageError(
                f"A message can be at most {self._limits.max_message_chars} characters long."
            )
        agent = self._agent
        if agent is None:
            raise ProviderNotConfiguredError

        user_message = await self._store_user_message(
            principal, thread_id, text, attachments, timezone_name=timezone_name
        )
        if self._capture is not None:
            # The user's own words only; a message that is just files has none.
            self._capture.capture_chat_message(
                user_id=principal.id,
                message_id=user_message.id,
                thread_id=thread_id,
                text=text,
                sent_at=user_message.created_at,
                timezone_name=timezone_name,
            )
        queue: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
        self._background.spawn(
            self._run(
                agent,
                principal,
                thread_id,
                UserText(text or user_message.content, attachments=tuple(attachments)),
                user_message.id,
                timezone_name,
                queue,
            ),
            name=f"chat-turn-{thread_id}",
        )
        return _drain(TurnStarted(user_message), queue)

    def _check_attachments(self, attachments: Sequence[Attachment]) -> None:
        limits = self._limits
        if len(attachments) > limits.max_attachments:
            raise InvalidAttachmentError(
                f"A message can carry at most {limits.max_attachments} files."
            )
        for attachment in attachments:
            if attachment.media_type not in ATTACHMENT_TYPES:
                raise InvalidAttachmentError(
                    f"{attachment.name} is not a supported file. Attach images or PDFs."
                )
            if not attachment.data:
                raise InvalidAttachmentError(f"{attachment.name} is empty.")
            if len(attachment.data) > limits.max_attachment_bytes:
                limit = _readable_size(limits.max_attachment_bytes)
                raise InvalidAttachmentError(f"{attachment.name} is larger than {limit}.")

    async def _store_user_message(
        self,
        principal: Principal,
        thread_id: uuid.UUID,
        text: str,
        attachments: Sequence[Attachment],
        *,
        timezone_name: str,
    ) -> ChatMessage:
        now = self._clock()
        async with transaction(self._session_factory) as session:
            chat = ChatRepository(session)
            thread = await existing_thread(chat, principal, thread_id, for_update=True)
            if turn_running(thread, now):
                raise ChatTurnInProgressError
            await self._usage.count_chat_message(session, principal.id, timezone_name=timezone_name)
            thread.turn_lease_until = now + self._limits.lease

            names = [attachment.name for attachment in attachments]
            content = text or f"Attached: {', '.join(names)}"
            if (
                thread.kind == ThreadKind.SIDE.value
                and thread.title == NEW_SIDE_THREAD_TITLE
                and await chat.count_messages(thread.id) == 0
            ):
                thread.title = title_from_text(content)
            metadata = MessageMetadata(
                attachments=[
                    AttachmentNote(
                        name=attachment.name,
                        media_type=attachment.media_type,
                        size_bytes=len(attachment.data),
                    )
                    for attachment in attachments
                ]
                or None
            )
            return await append_message(
                chat, thread, role=ChatRole.USER, content=content, metadata=metadata, now=now
            )

    async def _run(
        self,
        agent: AssistantAgent,
        principal: Principal,
        thread_id: uuid.UUID,
        current: UserText,
        current_message_id: uuid.UUID,
        timezone_name: str,
        queue: "asyncio.Queue[TurnEvent | None]",
    ) -> None:
        async def emit(event: ProgressEvent) -> None:
            await queue.put(event)

        final: TurnEvent
        released = False
        try:
            context = await self._load_context(principal, thread_id, current_message_id, current)
            turn = TurnContext(
                principal=principal,
                timezone_name=timezone_name,
                original_prompt=current.text,
                emit=emit,
                user_confirmed_action=_explicit_action_approval(current.text),
            )
            result = await agent.run(
                instructions=chat_instructions(self._toolbox.capabilities),
                context=chat_context(
                    now=self._clock(),
                    timezone_name=timezone_name,
                    user_name=principal.display_name,
                    connected_apps=context.connected_apps,
                    assistant_name=context.assistant_name,
                ),
                history=context.history,
                tools=self._toolbox.for_chat(),
                turn=turn,
                operation=LlmOperation.CHAT,
                call_context=LlmCallContext(origin=LlmCallOrigin.ASSISTANT, user_id=principal.id),
            )
            reply = result.text or (
                _PROPOSAL_FALLBACK if turn.proposal is not None else _EMPTY_REPLY_FALLBACK
            )
            metadata = MessageMetadata(
                browser_preview=turn.browser_preview,
                connect_link=turn.connect_link,
                job_application_draft=turn.job_application_draft,
                schedule_proposal=turn.proposal,
            )
            message = await self._store_reply(principal, thread_id, reply, metadata)
            released = True
            final = (
                TurnFinished(message)
                if message is not None
                else TurnFailed("NOT_FOUND", "The thread was deleted during the reply.")
            )
        except DomainError as error:
            logger.warning("chat_turn_failed", thread_id=str(thread_id), error_code=error.code)
            final = TurnFailed(error.code, error.message)
        except Exception:
            logger.exception("chat_turn_crashed", thread_id=str(thread_id))
            final = TurnFailed(UNEXPECTED_ERROR_CODE, _UNEXPECTED_ERROR_MESSAGE)
        finally:
            if not released:
                # Shielded so a cancelled turn still frees the thread.
                await asyncio.shield(self._release(thread_id))
        await queue.put(final)
        await queue.put(None)

    async def _load_context(
        self,
        principal: Principal,
        thread_id: uuid.UUID,
        current_message_id: uuid.UUID,
        current: UserText,
    ) -> _Context:
        async with self._session_factory() as session:
            messages, _ = await ChatRepository(session).recent_messages(
                thread_id, limit=self._limits.history_messages
            )
            connections = await ToolConnectionRepository(session).list_for_user(principal.id)
            user = await UserRepository(session).get(principal.id)
        connected = [
            row.toolkit_slug
            for row in connections
            if row.status == ToolConnectionStatus.CONNECTED.value
        ]
        history = [
            current if message.id == current_message_id else _as_history_item(message)
            for message in messages
        ]
        return _Context(
            history=history,
            connected_apps=_app_names(connected),
            assistant_name=user.assistant_name if user is not None else None,
        )

    async def _store_reply(
        self, principal: Principal, thread_id: uuid.UUID, reply: str, metadata: MessageMetadata
    ) -> ChatMessage | None:
        """Store the reply and free the thread, in one transaction."""
        async with transaction(self._session_factory) as session:
            chat = ChatRepository(session)
            thread = await chat.get_thread(principal.id, thread_id, for_update=True)
            if thread is None:
                return None
            thread.turn_lease_until = None
            return await append_message(
                chat,
                thread,
                role=ChatRole.ASSISTANT,
                content=reply,
                metadata=metadata,
                now=self._clock(),
            )

    async def _release(self, thread_id: uuid.UUID) -> None:
        try:
            async with transaction(self._session_factory) as session:
                await ChatRepository(session).release_turn(thread_id)
        except Exception:
            # The lease expires by itself; a failed release only delays the next turn.
            logger.exception("chat_turn_release_failed", thread_id=str(thread_id))


async def _drain(
    first: TurnEvent, queue: "asyncio.Queue[TurnEvent | None]"
) -> AsyncIterator[TurnEvent]:
    yield first
    while (event := await queue.get()) is not None:
        yield event


def _as_history_item(message: ChatMessage) -> UserText | AssistantText:
    if message.role != ChatRole.USER.value:
        return AssistantText(message.content)
    notes = MessageMetadata.from_json(message.metadata_).attachments
    if not notes:
        return UserText(message.content)
    # Earlier files are not sent again; the model learns only that they were attached.
    names = ", ".join(note.name for note in notes)
    return UserText(f"{message.content}\n\n[Attached earlier: {names}]")


def _readable_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):g} MB"
    if size >= 1024:
        return f"{size / 1024:g} KB"
    return f"{size} bytes"


def _app_names(slugs: Sequence[str]) -> list[str]:
    return sorted(spec.name for slug in slugs if (spec := find_tool(slug)) is not None)


def _explicit_action_approval(text: str) -> bool:
    """True when a short user message clearly approves executing a pending action."""
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    if not cleaned or len(cleaned) > 80:
        return False
    framed = f" {cleaned} "
    if any(blocker in framed for blocker in _APPROVAL_BLOCKERS):
        return False
    return any(cleaned.startswith(prefix) for prefix in _APPROVAL_PREFIXES)
