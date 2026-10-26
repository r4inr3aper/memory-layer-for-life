import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    ColumnElement,
    Float,
    cast,
    delete,
    exists,
    func,
    literal_column,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert

from app.db.base import new_uuid
from app.domain.enums import ChatRole, ThreadKind
from app.models.app_user import AppUser
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.repositories.base import BaseRepository

# Matches are marked in a snippet with these, so the app can show them in bold.
HIGHLIGHT = "StartSel=<<, StopSel=>>, MaxWords=30, MinWords=12, MaxFragments=1"


@dataclass(frozen=True, slots=True)
class ThreadToCapture:
    """A thread with messages the memory pipeline has not seen, gone quiet."""

    id: uuid.UUID
    user_id: uuid.UUID
    updated_at: datetime
    captured_through: datetime | None
    capture_enabled: bool
    timezone: str | None


def _has_messages() -> ColumnElement[bool]:
    return exists(select(ChatMessage.id).where(ChatMessage.thread_id == ChatThread.id))


def _not_captured() -> ColumnElement[bool]:
    return or_(
        ChatThread.memory_captured_through.is_(None),
        ChatThread.updated_at > ChatThread.memory_captured_through,
    )


class ChatRepository(BaseRepository):
    """Persistence of threads and their messages.

    Every thread lookup is scoped to its owner, so a thread of another user reads as
    missing rather than forbidden.
    """

    # --- Threads -----------------------------------------------------------------------

    async def add_thread(self, thread: ChatThread) -> ChatThread:
        self._session.add(thread)
        await self._session.flush()
        return thread

    async def get_thread(
        self, user_id: uuid.UUID, thread_id: uuid.UUID, *, for_update: bool = False
    ) -> ChatThread | None:
        query = select(ChatThread).where(ChatThread.id == thread_id, ChatThread.user_id == user_id)
        if for_update:
            query = query.with_for_update()
        result: ChatThread | None = await self._session.scalar(query)
        return result

    async def existing_thread_ids(
        self, user_id: uuid.UUID, thread_ids: Collection[uuid.UUID]
    ) -> set[uuid.UUID]:
        """Which of these threads the user still has."""
        if not thread_ids:
            return set()
        rows = await self._session.scalars(
            select(ChatThread.id).where(
                ChatThread.user_id == user_id, ChatThread.id.in_(thread_ids)
            )
        )
        return set(rows)

    async def main_thread(self, user_id: uuid.UUID) -> ChatThread | None:
        result: ChatThread | None = await self._session.scalar(
            select(ChatThread).where(
                ChatThread.user_id == user_id, ChatThread.kind == ThreadKind.MAIN.value
            )
        )
        return result

    async def ensure_main_thread(
        self, user_id: uuid.UUID, *, title: str, now: datetime
    ) -> ChatThread:
        """Return the user's main thread, creating it when it does not exist yet.

        Concurrent callers race on the partial unique index, and the loser reads the row
        the winner wrote.
        """
        statement = (
            insert(ChatThread)
            .values(
                id=new_uuid(),
                user_id=user_id,
                kind=ThreadKind.MAIN.value,
                title=title,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[ChatThread.user_id], index_where=text("kind = 'main'")
            )
        )
        await self._session.execute(statement)
        thread = await self.main_thread(user_id)
        if thread is None:  # pragma: no cover - the row exists after the insert above
            raise RuntimeError("main thread missing after insert")
        return thread

    async def list_threads(
        self,
        user_id: uuid.UUID,
        *,
        kind: ThreadKind | None,
        limit: int,
        offset: int,
        include_empty_side: bool = True,
    ) -> tuple[list[ChatThread], int]:
        """Threads with the most recent activity first. ``include_empty_side=False`` leaves
        out side threads without a message."""
        conditions = [ChatThread.user_id == user_id]
        if kind is not None:
            conditions.append(ChatThread.kind == kind.value)
        if not include_empty_side:
            conditions.append(or_(ChatThread.kind != ThreadKind.SIDE.value, _has_messages()))
        total = await self._session.scalar(
            select(func.count()).select_from(ChatThread).where(*conditions)
        )
        rows = await self._session.scalars(
            select(ChatThread)
            .where(*conditions)
            .order_by(ChatThread.updated_at.desc(), ChatThread.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def empty_side_thread(self, user_id: uuid.UUID) -> ChatThread | None:
        """The user's most recent side thread without a message, locked, if any."""
        result: ChatThread | None = await self._session.scalar(
            select(ChatThread)
            .where(
                ChatThread.user_id == user_id,
                ChatThread.kind == ThreadKind.SIDE.value,
                ~_has_messages(),
            )
            .order_by(ChatThread.updated_at.desc(), ChatThread.id.desc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return result

    async def name_thread(self, thread_id: uuid.UUID, title: str) -> bool:
        """Give a side thread the title the model wrote, unless it already has one. A title
        is not activity: ``updated_at`` stays. Returns whether the title changed."""
        result = await self._session.execute(
            update(ChatThread)
            .where(
                ChatThread.id == thread_id,
                ChatThread.kind == ThreadKind.SIDE.value,
                ChatThread.title_generated.is_(False),
            )
            .values(title=title, title_generated=True, updated_at=ChatThread.updated_at)
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    # --- Memory capture (ADR-048) ------------------------------------------------------

    async def threads_to_capture(
        self, *, quiet_before: datetime, limit: int
    ) -> list[ThreadToCapture]:
        """Threads with activity since their last capture and none since ``quiet_before``,
        longest quiet first, with their owner's capture switch and timezone."""
        rows = await self._session.execute(
            select(
                ChatThread.id,
                ChatThread.user_id,
                ChatThread.updated_at,
                ChatThread.memory_captured_through,
                AppUser.memory_capture_enabled,
                AppUser.timezone,
            )
            .join(AppUser, AppUser.id == ChatThread.user_id)
            .where(_not_captured(), ChatThread.updated_at <= quiet_before)
            .order_by(ChatThread.updated_at, ChatThread.id)
            .limit(limit)
        )
        return [
            ThreadToCapture(
                id=row[0],
                user_id=row[1],
                updated_at=row[2],
                captured_through=row[3],
                capture_enabled=bool(row[4]),
                timezone=row[5],
            )
            for row in rows
        ]

    async def next_capture_activity(self) -> datetime | None:
        """The last activity of the thread that has waited longest for a capture."""
        result: datetime | None = await self._session.scalar(
            select(func.min(ChatThread.updated_at)).where(_not_captured())
        )
        return result

    async def messages_after(
        self, thread_id: uuid.UUID, *, after: datetime | None, limit: int
    ) -> list[ChatMessage]:
        """A thread's messages after ``after`` (all, when None), oldest first."""
        conditions = [ChatMessage.thread_id == thread_id]
        if after is not None:
            conditions.append(ChatMessage.created_at > after)
        rows = await self._session.scalars(
            select(ChatMessage)
            .where(*conditions)
            .order_by(ChatMessage.created_at, ChatMessage.id)
            .limit(limit)
        )
        return list(rows)

    async def last_assistant_text(self, thread_id: uuid.UUID, *, before: datetime) -> str | None:
        """The text of the thread's last assistant message before ``before``."""
        result: str | None = await self._session.scalar(
            select(ChatMessage.content)
            .where(
                ChatMessage.thread_id == thread_id,
                ChatMessage.role == ChatRole.ASSISTANT.value,
                ChatMessage.created_at < before,
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
        return result

    async def mark_captured(self, thread_id: uuid.UUID, through: datetime) -> None:
        """Move the thread's capture watermark forward. Never backward, and never moves
        ``updated_at``: being captured is not activity."""
        await self._session.execute(
            update(ChatThread)
            .where(
                ChatThread.id == thread_id,
                or_(
                    ChatThread.memory_captured_through.is_(None),
                    ChatThread.memory_captured_through < through,
                ),
            )
            .values(memory_captured_through=through, updated_at=ChatThread.updated_at)
            .execution_options(synchronize_session=False)
        )

    async def delete_thread(self, thread: ChatThread) -> None:
        """Delete a thread. Its messages go with it, by the foreign key's cascade."""
        await self._session.delete(thread)
        await self._session.flush()

    async def touch_thread(self, thread_id: uuid.UUID, now: datetime) -> None:
        await self._session.execute(
            update(ChatThread).where(ChatThread.id == thread_id).values(updated_at=now)
        )

    # --- Messages ----------------------------------------------------------------------

    async def add_message(self, message: ChatMessage) -> ChatMessage:
        self._session.add(message)
        await self._session.flush()
        return message

    async def get_message(
        self, thread_id: uuid.UUID, message_id: uuid.UUID, *, for_update: bool = False
    ) -> ChatMessage | None:
        query = select(ChatMessage).where(
            ChatMessage.id == message_id, ChatMessage.thread_id == thread_id
        )
        if for_update:
            query = query.with_for_update()
        result: ChatMessage | None = await self._session.scalar(query)
        return result

    async def count_messages(self, thread_id: uuid.UUID) -> int:
        total = await self._session.scalar(
            select(func.count()).select_from(ChatMessage).where(ChatMessage.thread_id == thread_id)
        )
        return int(total or 0)

    async def recent_messages(
        self, thread_id: uuid.UUID, *, limit: int, offset: int = 0
    ) -> tuple[list[ChatMessage], int]:
        """The most recent ``limit`` messages, returned oldest first.

        ``offset`` skips that many of the newest messages, which pages back in time.
        """
        total = await self.count_messages(thread_id)
        rows = await self._session.scalars(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(reversed(list(rows))), total

    async def search_messages(
        self, user_id: uuid.UUID, tsquery_source: str, *, limit: int
    ) -> list[tuple[ChatMessage, ChatThread, str]]:
        """The user's messages matching any of the query's terms (``any_term_tsquery``),
        best first, each with its thread and a highlighted snippet."""
        english: ColumnElement[str] = literal_column("'english'::regconfig")
        simple: ColumnElement[str] = literal_column("'simple'::regconfig")
        tsquery = func.to_tsquery(english, tsquery_source).op("||")(
            func.to_tsquery(simple, tsquery_source)
        )
        rank = cast(func.ts_rank_cd(ChatMessage.search_document, tsquery, 32), Float)
        snippet = func.ts_headline(english, ChatMessage.content, tsquery, HIGHLIGHT)
        rows = await self._session.execute(
            select(ChatMessage, ChatThread, snippet)
            .join(ChatThread, ChatThread.id == ChatMessage.thread_id)
            .where(ChatThread.user_id == user_id, ChatMessage.search_document.op("@@")(tsquery))
            .order_by(rank.desc(), ChatMessage.created_at.desc(), ChatMessage.id)
            .limit(limit)
        )
        return [(row[0], row[1], str(row[2])) for row in rows]

    async def delete_messages(self, thread_id: uuid.UUID) -> int:
        result = await self._session.execute(
            delete(ChatMessage).where(ChatMessage.thread_id == thread_id)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def release_turn(self, thread_id: uuid.UUID) -> None:
        """Free the thread's reply lease."""
        await self._session.execute(
            update(ChatThread).where(ChatThread.id == thread_id).values(turn_lease_until=None)
        )
