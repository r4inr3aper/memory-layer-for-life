"""Threads and messages.

Every operation is scoped to the signed-in user: a thread of someone else reads as
missing. A user's main thread is created on first use and cannot be deleted; side
threads come and go.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import ChatRole, ProposalStatus, ThreadKind
from app.domain.errors import (
    ChatTurnInProgressError,
    ProtectedThreadError,
    RecordNotFoundError,
    ScheduleProposalError,
)
from app.domain.principal import Principal
from app.domain.retrieval import any_term_tsquery, lexical_terms, normalize_query
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.repositories.chat_repository import ChatRepository
from app.schemas.message_metadata import MessageMetadata, ScheduleProposal

MAIN_THREAD_TITLE: Final = "Main Chat"
NEW_SIDE_THREAD_TITLE: Final = "New chat"
_MAX_TITLE_CHARS: Final = 60
_WHITESPACE: Final = re.compile(r"\s+")


def title_from_text(text: str) -> str:
    """A thread title from the first message: one line, cut at a word boundary."""
    line = _WHITESPACE.sub(" ", text).strip()
    if len(line) <= _MAX_TITLE_CHARS:
        return line or NEW_SIDE_THREAD_TITLE
    cut = line[: _MAX_TITLE_CHARS - 1].rsplit(" ", 1)[0] or line[: _MAX_TITLE_CHARS - 1]
    return f"{cut}…"


def turn_running(thread: ChatThread, now: datetime) -> bool:
    """Whether a reply holds the thread's lease right now, in any process."""
    return thread.turn_lease_until is not None and thread.turn_lease_until > now


async def append_message(
    chat: ChatRepository,
    thread: ChatThread,
    *,
    role: ChatRole,
    content: str,
    metadata: MessageMetadata | None = None,
    now: datetime,
) -> ChatMessage:
    """Add a message to a thread loaded in the same session, and mark the thread active."""
    message = ChatMessage(
        id=new_uuid(),
        thread_id=thread.id,
        role=role.value,
        content=content,
        metadata_=(metadata or MessageMetadata()).to_json(),
        created_at=now,
        updated_at=now,
    )
    await chat.add_message(message)
    thread.updated_at = now
    return message


@dataclass(frozen=True, slots=True)
class MessageHit:
    message_id: uuid.UUID
    thread_id: uuid.UUID
    thread_title: str
    thread_kind: ThreadKind
    role: ChatRole
    snippet: str
    created_at: datetime


class ChatService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, clock: Clock = utc_now
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def search_messages(
        self, principal: Principal, query: str, *, limit: int
    ) -> list[MessageHit]:
        """The user's chat messages (theirs and the assistant's) containing the query's
        words, best first. A query of stopwords only finds nothing."""
        terms = lexical_terms(normalize_query(query))
        if not terms:
            return []
        async with self._session_factory() as session:
            rows = await ChatRepository(session).search_messages(
                principal.id, any_term_tsquery(terms), limit=limit
            )
        return [
            MessageHit(
                message_id=message.id,
                thread_id=thread.id,
                thread_title=thread.title,
                thread_kind=ThreadKind(thread.kind),
                role=ChatRole(message.role),
                snippet=snippet,
                created_at=message.created_at,
            )
            for message, thread, snippet in rows
        ]

    async def list_threads(
        self, principal: Principal, *, kind: ThreadKind | None, limit: int, offset: int
    ) -> tuple[list[ChatThread], int]:
        async with self._session_factory() as session:
            return await ChatRepository(session).list_threads(
                principal.id, kind=kind, limit=limit, offset=offset
            )

    async def ensure_main_thread(self, principal: Principal) -> ChatThread:
        async with transaction(self._session_factory) as session:
            return await ChatRepository(session).ensure_main_thread(
                principal.id, title=MAIN_THREAD_TITLE, now=self._clock()
            )

    async def create_side_thread(self, principal: Principal, *, title: str | None) -> ChatThread:
        now = self._clock()
        async with transaction(self._session_factory) as session:
            return await ChatRepository(session).add_thread(
                ChatThread(
                    id=new_uuid(),
                    user_id=principal.id,
                    kind=ThreadKind.SIDE.value,
                    title=title_from_text(title) if title else NEW_SIDE_THREAD_TITLE,
                    created_at=now,
                    updated_at=now,
                )
            )

    async def get_thread(self, principal: Principal, thread_id: uuid.UUID) -> ChatThread:
        async with self._session_factory() as session:
            return await existing_thread(ChatRepository(session), principal, thread_id)

    async def delete_thread(self, principal: Principal, thread_id: uuid.UUID) -> None:
        async with transaction(self._session_factory) as session:
            chat = ChatRepository(session)
            thread = await existing_thread(chat, principal, thread_id, for_update=True)
            if thread.kind == ThreadKind.MAIN.value:
                raise ProtectedThreadError
            await chat.delete_thread(thread)

    async def clear_messages(self, principal: Principal, thread_id: uuid.UUID) -> None:
        """Delete every message of a thread and keep the thread. Refused while a reply runs
        in it, which would otherwise write into the cleared thread."""
        now = self._clock()
        async with transaction(self._session_factory) as session:
            chat = ChatRepository(session)
            thread = await existing_thread(chat, principal, thread_id, for_update=True)
            if turn_running(thread, now):
                raise ChatTurnInProgressError
            await chat.delete_messages(thread.id)
            thread.updated_at = now

    async def list_messages(
        self, principal: Principal, thread_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[ChatMessage], int]:
        async with self._session_factory() as session:
            chat = ChatRepository(session)
            await existing_thread(chat, principal, thread_id)
            return await chat.recent_messages(thread_id, limit=limit, offset=offset)

    async def dismiss_proposal(
        self, principal: Principal, thread_id: uuid.UUID, message_id: uuid.UUID
    ) -> ChatMessage:
        """Turn down a schedule the assistant proposed. Nothing was created, so nothing is
        removed; the proposal is marked dismissed so it cannot be confirmed later."""
        async with transaction(self._session_factory) as session:
            chat = ChatRepository(session)
            await existing_thread(chat, principal, thread_id)
            message = await existing_message(chat, thread_id, message_id)
            metadata = MessageMetadata.from_json(message.metadata_)
            proposal = pending_proposal(metadata)
            metadata.schedule_proposal = proposal.model_copy(
                update={"status": ProposalStatus.DISMISSED}
            )
            message.metadata_ = metadata.to_json()
            message.updated_at = self._clock()
            return message


async def existing_thread(
    chat: ChatRepository, principal: Principal, thread_id: uuid.UUID, *, for_update: bool = False
) -> ChatThread:
    thread = await chat.get_thread(principal.id, thread_id, for_update=for_update)
    if thread is None:
        raise RecordNotFoundError("Thread", str(thread_id))
    return thread


async def existing_message(
    chat: ChatRepository, thread_id: uuid.UUID, message_id: uuid.UUID
) -> ChatMessage:
    """A message of a thread, locked for the rest of the transaction."""
    message = await chat.get_message(thread_id, message_id, for_update=True)
    if message is None:
        raise RecordNotFoundError("Message", str(message_id))
    return message


def pending_proposal(metadata: MessageMetadata) -> ScheduleProposal:
    proposal = metadata.schedule_proposal
    if proposal is None:
        raise ScheduleProposalError("This message does not propose a schedule.")
    if proposal.status is not ProposalStatus.PENDING:
        raise ScheduleProposalError(f"This schedule proposal was already {proposal.status.value}.")
    return proposal
