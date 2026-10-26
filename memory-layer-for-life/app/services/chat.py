"""Threads and messages.

Every operation is scoped to the signed-in user: a thread of someone else reads as
missing. A user's main thread is created on first use and cannot be deleted; side
threads come and go.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.conversation import heuristic_title
from app.domain.enums import ChatRole, MemoryStatus, MemoryType, ProposalStatus, ThreadKind
from app.domain.errors import (
    AttachmentUnavailableError,
    ChatTurnInProgressError,
    IntegrationError,
    IntegrationNotConfiguredError,
    JobApplicationDraftError,
    ProtectedThreadError,
    RecordNotFoundError,
    ScheduleProposalError,
)
from app.domain.memory_policy import display_title
from app.domain.principal import Principal
from app.domain.retrieval import any_term_tsquery, lexical_terms, normalize_query
from app.domain.tool_catalog import find_tool
from app.integrations.composio import SERVICE_NAME, ComposioClient
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.repositories.chat_repository import ChatRepository
from app.repositories.memory_repository import MemoryRepository
from app.schemas.message_metadata import JobApplicationDraft, MessageMetadata, ScheduleProposal
from app.services.attachments import AppAttachments, references
from app.services.tool_connections import ToolConnectionService

MAIN_THREAD_TITLE: Final = "Main Chat"
NEW_SIDE_THREAD_TITLE: Final = "New chat"


def title_from_text(text: str) -> str:
    """A side thread's title from its first message, until the memory pipeline names the
    conversation (ADR-048): links named for what they are, polite openings dropped, one
    short line."""
    return heuristic_title(text) or NEW_SIDE_THREAD_TITLE


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
class SavedMemory:
    """A memory a chat message is evidence for."""

    memory_id: uuid.UUID
    title: str
    memory_type: MemoryType
    status: MemoryStatus


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
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        composio: ComposioClient | None = None,
        connections: ToolConnectionService | None = None,
        attachments: AppAttachments | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._composio = composio
        self._connections = connections
        self._attachments = attachments
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
        """Threads with the most recent activity first. A side thread nobody has written in
        yet is left out: it has nothing to show but "New chat"."""
        async with self._session_factory() as session:
            return await ChatRepository(session).list_threads(
                principal.id, kind=kind, limit=limit, offset=offset, include_empty_side=False
            )

    async def ensure_main_thread(self, principal: Principal) -> ChatThread:
        async with transaction(self._session_factory) as session:
            return await ChatRepository(session).ensure_main_thread(
                principal.id, title=MAIN_THREAD_TITLE, now=self._clock()
            )

    async def create_side_thread(self, principal: Principal, *, title: str | None) -> ChatThread:
        """A new side thread. Without a title, an earlier side thread nobody wrote in is
        reused, so starting a chat and leaving it never piles up empty "New chat" rows."""
        now = self._clock()
        async with transaction(self._session_factory) as session:
            chat = ChatRepository(session)
            if not title:
                empty = await chat.empty_side_thread(principal.id)
                if empty is not None:
                    empty.updated_at = now
                    return empty
            return await chat.add_thread(
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

    async def saved_memories(
        self, principal: Principal, messages: Sequence[ChatMessage]
    ) -> dict[uuid.UUID, list[SavedMemory]]:
        """The memories each of the user's messages is evidence for, by message id, so the
        app can show what was remembered beside the message and undo it (ADR-048)."""
        ids = {message.id for message in messages if message.role == ChatRole.USER.value}
        async with self._session_factory() as session:
            rows = await MemoryRepository(session).saved_from_chat_messages(principal.id, ids)
        saved: dict[uuid.UUID, list[SavedMemory]] = {}
        for message_id, memory in rows:
            saved.setdefault(uuid.UUID(message_id), []).append(
                SavedMemory(
                    memory_id=memory.id,
                    title=display_title(memory.content, memory.metadata_),
                    memory_type=MemoryType(memory.memory_type),
                    status=MemoryStatus(memory.status),
                )
            )
        return saved

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

    async def send_job_application_draft(
        self, principal: Principal, thread_id: uuid.UUID, message_id: uuid.UUID
    ) -> ChatMessage:
        """Send an email draft card the assistant prepared.

        The first transaction marks the draft as sending so a second tap in parallel sees
        it as unavailable. The final status (sent or failed) is then written back.
        """
        draft = await self._mark_job_draft_sending(principal, thread_id, message_id)
        try:
            await self._execute_job_draft(principal, draft)
        except Exception as error:
            message = await self._finish_job_draft(
                principal,
                thread_id,
                message_id,
                status="failed",
                error_message=self._job_draft_error_message(error),
            )
            return message
        return await self._finish_job_draft(
            principal,
            thread_id,
            message_id,
            status="sent",
            error_message=None,
        )

    async def _mark_job_draft_sending(
        self, principal: Principal, thread_id: uuid.UUID, message_id: uuid.UUID
    ) -> JobApplicationDraft:
        now = self._clock()
        async with transaction(self._session_factory) as session:
            chat = ChatRepository(session)
            await existing_thread(chat, principal, thread_id)
            message = await existing_message(chat, thread_id, message_id)
            metadata = MessageMetadata.from_json(message.metadata_)
            draft = sendable_job_application_draft(metadata)
            metadata.job_application_draft = draft.model_copy(
                update={"status": "sending", "error_message": None}
            )
            message.metadata_ = metadata.to_json()
            message.updated_at = now
            return draft

    async def _finish_job_draft(
        self,
        principal: Principal,
        thread_id: uuid.UUID,
        message_id: uuid.UUID,
        *,
        status: str,
        error_message: str | None,
    ) -> ChatMessage:
        now = self._clock()
        async with transaction(self._session_factory) as session:
            chat = ChatRepository(session)
            await existing_thread(chat, principal, thread_id)
            message = await existing_message(chat, thread_id, message_id)
            metadata = MessageMetadata.from_json(message.metadata_)
            draft = metadata.job_application_draft
            if draft is None:
                raise JobApplicationDraftError("This message has no job application draft.")
            metadata.job_application_draft = draft.model_copy(
                update={
                    "status": status,
                    "error_message": error_message,
                    "sent_at": now if status == "sent" else None,
                }
            )
            message.metadata_ = metadata.to_json()
            message.updated_at = now
            return message

    async def _execute_job_draft(self, principal: Principal, draft: JobApplicationDraft) -> None:
        composio = self._composio
        if composio is None or self._connections is None:
            raise IntegrationNotConfiguredError(SERVICE_NAME, "COMPOSIO_API_KEY")
        app = draft.delivery_app.strip().lower()
        spec = find_tool(app)
        if spec is None:
            raise IntegrationError(SERVICE_NAME, f"Unknown app '{app}' in this draft.")
        if not draft.send_tool_slug.strip().lower().startswith(f"{app}_"):
            raise IntegrationError(
                SERVICE_NAME,
                f"The draft's send action does not belong to {spec.name}.",
            )
        accounts = await self._connections.active_accounts(principal)
        account_ids = accounts.get(app, [])
        if not account_ids:
            raise IntegrationError(
                SERVICE_NAME, f"{spec.name} is not connected. Connect it and try again."
            )
        arguments: dict[str, object] = dict(draft.send_arguments)
        if references(arguments):
            # The files the card showed, staged for this send; a deleted one stops it.
            if self._attachments is None:
                raise AttachmentUnavailableError("Files cannot be attached right now.")
            arguments = await self._attachments.stage(
                principal.id, arguments, toolkit=app, tool_slug=draft.send_tool_slug
            )
        session_id = await composio.create_session(str(principal.id), app, account_ids)
        execution = await composio.execute_tool(session_id, draft.send_tool_slug, arguments)
        if not execution.successful:
            raise IntegrationError(SERVICE_NAME, execution.error or "could not send the email.")

    def _job_draft_error_message(self, error: Exception) -> str:
        if isinstance(error, IntegrationError):
            return error.message
        if isinstance(error, JobApplicationDraftError | AttachmentUnavailableError):
            return error.message
        return "Could not send the draft right now. Please try again."


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


def sendable_job_application_draft(metadata: MessageMetadata) -> JobApplicationDraft:
    draft = metadata.job_application_draft
    if draft is None:
        raise JobApplicationDraftError("This message does not include a job application draft.")
    if draft.status not in {"pending", "failed"}:
        raise JobApplicationDraftError(f"This job application draft was already {draft.status}.")
    return draft
