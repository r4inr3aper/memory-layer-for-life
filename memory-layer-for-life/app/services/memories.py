"""Memories as their owner manages them in the app: read with their evidence and history,
write by hand, accept, retract and restore, correct, edit, merge, replace, and delete.

Every change is the owner's and is recorded in the memory's history (``memory_events``),
in the same transaction as the change.

* Correcting the text never rewrites a memory: it makes a new ``active`` version, written
  by the user, that supersedes the old one and keeps its evidence and entities. The old
  text stays inspectable in the history. Amounts and dates read from the old text are
  not carried over, since they described it.
* Kind and sensitivity change in place.
* Merging a duplicate gives the kept memory the duplicate's evidence; replacing an
  out-of-date memory does not. Either way the other memory becomes ``superseded`` (a
  ``supersedes`` relation records by which) and the kept one counts as reviewed.
* Deleting a memory deletes it with everything it replaced (its older versions and the
  memories merged into it or replaced by it), their history, and their embeddings. The
  messages they came from stay: they are the chat's, and deleting a chat is separate.
* Marking a memory sensitive deletes its embeddings at once: sensitive memories are never
  sent to a model provider (ADR-044).
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import (
    MemoryEventAction,
    MemoryOrigin,
    MemoryState,
    MemoryStatus,
    MemoryType,
    RelationType,
    Sensitivity,
)
from app.domain.errors import InvalidMemoryChangeError, MemoryStateError, RecordNotFoundError
from app.domain.life_state import LIFE_TYPES
from app.domain.memory_review import ensure_can_restore, ensure_live
from app.domain.normalization import normalize_for_matching
from app.domain.principal import Principal
from app.models.memory import Memory
from app.repositories.chat_repository import ChatRepository
from app.repositories.embedding_repository import EmbeddingRepository
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory_metadata import MemoryMetadata
from app.services.queries import (
    MemoryDetailView,
    MemoryView,
    PageResult,
    chat_thread_id,
    memory_detail,
)

MAX_CONTENT_CHARS: Final = 2000
# How many memories one bulk accept may name.
MAX_BULK: Final = 100


@dataclass(frozen=True, slots=True)
class NewMemory:
    """A memory the user writes themselves. A to-do may come with a due date and a
    reminder."""

    memory_type: MemoryType
    content: str
    sensitive: bool = False
    due_on: date | None = None
    remind_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MemoryChanges:
    """An edit. None leaves a field as it is. New text makes a new version. The due date
    and the reminder can be cleared, so ``*_given`` tells clearing apart from leaving."""

    content: str | None = None
    memory_type: MemoryType | None = None
    sensitive: bool | None = None
    due_on: date | None = None
    due_on_given: bool = False
    remind_at: datetime | None = None
    remind_at_given: bool = False


@dataclass(frozen=True, slots=True)
class MemoryEventView:
    id: uuid.UUID
    action: MemoryEventAction
    details: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryVersionView:
    """An older version of a memory, or a memory merged into it or replaced by it."""

    id: uuid.UUID
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MyMemoryDetail:
    detail: MemoryDetailView
    history: tuple[MemoryEventView, ...]
    # Newest first.
    replaced: tuple[MemoryVersionView, ...]
    # The memory that replaced this one, when it is superseded.
    replaced_by_id: uuid.UUID | None


class MemoryService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, clock: Clock = utc_now
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    # --- Reading -----------------------------------------------------------------------

    async def list_memories(
        self,
        principal: Principal,
        *,
        statuses: Collection[MemoryStatus],
        memory_type: MemoryType | None,
        oldest_first: bool,
        limit: int,
        offset: int,
    ) -> PageResult[MemoryView]:
        async with self._session_factory() as session:
            memories, total = await MemoryRepository(session).list_memories(
                owner_id=principal.id,
                statuses=statuses,
                memory_type=memory_type,
                oldest_first=oldest_first,
                limit=limit,
                offset=offset,
            )
        return PageResult(items=tuple(MemoryView.of(memory) for memory in memories), total=total)

    async def get(self, principal: Principal, memory_id: uuid.UUID) -> MyMemoryDetail:
        """A memory with its evidence (and the chats it came from, while they exist), its
        entities, its history, and what it replaced or what replaced it."""
        async with self._session_factory() as session:
            memories = MemoryRepository(session)
            memory = await memories.get_with_provenance(memory_id, owner_id=principal.id)
            if memory is None:
                raise RecordNotFoundError("Memory", str(memory_id))
            threads = {
                thread_id
                for source in memory.sources
                if (thread_id := chat_thread_id(source.raw_message)) is not None
            }
            live_threads = await ChatRepository(session).existing_thread_ids(principal.id, threads)
            replaced = await memories.get_many(await memories.replaced_by([memory.id]))
            return MyMemoryDetail(
                detail=memory_detail(memory, live_threads=live_threads),
                history=tuple(
                    MemoryEventView(
                        id=event.id,
                        action=MemoryEventAction(event.action),
                        details=dict(event.details),
                        created_at=event.created_at,
                    )
                    for event in await memories.events(memory.id)
                ),
                replaced=tuple(
                    MemoryVersionView(id=old.id, content=old.content, created_at=old.created_at)
                    for old in sorted(replaced, key=lambda old: old.created_at, reverse=True)
                ),
                replaced_by_id=(
                    await memories.successor_of(memory.id)
                    if memory.status == MemoryStatus.SUPERSEDED.value
                    else None
                ),
            )

    # --- Writing -----------------------------------------------------------------------

    async def create(self, principal: Principal, new: NewMemory) -> MemoryView:
        """Save a memory the user wrote. It is ``active``: the user is the source. A to-do
        (a task, plan, goal, ...) starts open."""
        content = clean_content(new.content)
        now = self._clock()
        if new.remind_at is not None and new.remind_at <= now:
            raise InvalidMemoryChangeError("That time has already passed. Pick a time later.")
        metadata = user_metadata(sensitive=new.sensitive)
        if new.memory_type in LIFE_TYPES:
            metadata["state"] = MemoryState.OPEN.value
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            memory = new_user_memory(
                owner_id=principal.id,
                memory_type=new.memory_type,
                content=content,
                metadata=metadata,
                now=now,
            )
            memory.due_on = new.due_on
            memory.remind_at = new.remind_at
            await memories.add_memories([memory])
            await memories.add_event(memory.id, MemoryEventAction.CREATED, now=now)
            return MemoryView.of(memory)

    async def accept(self, principal: Principal, memory_id: uuid.UUID) -> MemoryView:
        """Confirm a proposed memory. Accepting an accepted one changes nothing."""
        now = self._clock()
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            memory = await owned_memory(memories, principal, memory_id)
            status = MemoryStatus(memory.status)
            ensure_live(status)
            if status is MemoryStatus.PROPOSED:
                memory.status = MemoryStatus.ACTIVE.value
                memory.updated_at = now
                await memories.add_event(memory.id, MemoryEventAction.ACCEPTED, now=now)
            return MemoryView.of(memory)

    async def accept_many(self, principal: Principal, memory_ids: Collection[uuid.UUID]) -> int:
        """Accept several proposed memories at once. Ids that are not the user's or not
        proposed are skipped. Returns how many were accepted."""
        if len(memory_ids) > MAX_BULK:
            raise InvalidMemoryChangeError(f"Accept at most {MAX_BULK} memories at a time.")
        now = self._clock()
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            accepted = 0
            for memory in (await memories.lock_owned(set(memory_ids), principal.id)).values():
                if memory.status != MemoryStatus.PROPOSED.value:
                    continue
                memory.status = MemoryStatus.ACTIVE.value
                memory.updated_at = now
                await memories.add_event(memory.id, MemoryEventAction.ACCEPTED, now=now)
                accepted += 1
            return accepted

    async def retract(self, principal: Principal, memory_id: uuid.UUID) -> MemoryView:
        """Mark a memory as wrong. It is kept as history and never used again."""
        now = self._clock()
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            memory = await owned_memory(memories, principal, memory_id)
            status = MemoryStatus(memory.status)
            if status is MemoryStatus.RETRACTED:
                return MemoryView.of(memory)
            ensure_live(status)
            memory.status = MemoryStatus.RETRACTED.value
            memory.updated_at = now
            await memories.add_event(
                memory.id, MemoryEventAction.RETRACTED, now=now, details={"from": status.value}
            )
            return MemoryView.of(memory)

    async def restore(self, principal: Principal, memory_id: uuid.UUID) -> MemoryView:
        """Bring back a memory marked as wrong, as accepted: the user has looked at it."""
        now = self._clock()
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            memory = await owned_memory(memories, principal, memory_id)
            status = MemoryStatus(memory.status)
            ensure_can_restore(status)
            if status is not MemoryStatus.RETRACTED:
                return MemoryView.of(memory)
            memory.status = MemoryStatus.ACTIVE.value
            memory.updated_at = now
            await memories.add_event(memory.id, MemoryEventAction.RESTORED, now=now)
            return MemoryView.of(memory)

    async def change(
        self, principal: Principal, memory_id: uuid.UUID, changes: MemoryChanges
    ) -> MemoryView:
        """Edit a memory. New text makes a new version (whose id the result carries);
        kind, sensitivity, the due date, and the reminder change in place."""
        now = self._clock()
        if changes.remind_at_given and changes.remind_at is not None and changes.remind_at <= now:
            raise InvalidMemoryChangeError("That time has already passed. Pick a time later.")
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            memory = await owned_memory(memories, principal, memory_id)
            ensure_live(MemoryStatus(memory.status))
            if changes.remind_at_given and changes.remind_at and memory.closed_at is not None:
                raise MemoryStateError("This is already closed. Reopen it to set a reminder.")
            content = clean_content(changes.content) if changes.content is not None else None
            if content is not None and content != memory.content:
                corrected = await self._correct(memories, memory, content, changes, now)
                return MemoryView.of(corrected)

            edited = _apply_in_place(memory, changes)
            if not edited:
                raise InvalidMemoryChangeError("Nothing to change.")
            memory.updated_at = now
            if edited.get("sensitive", {}).get("to") is True:
                await EmbeddingRepository(session).delete_for(memory.id)
            action = (
                MemoryEventAction.SCHEDULED
                if set(edited) <= _SCHEDULE_FIELDS
                else MemoryEventAction.EDITED
            )
            await memories.add_event(memory.id, action, now=now, details={"changes": edited})
            return MemoryView.of(memory)

    async def merge(
        self, principal: Principal, memory_id: uuid.UUID, duplicate_id: uuid.UUID
    ) -> MemoryView:
        """Merge a duplicate into this memory: it takes the duplicate's evidence and
        entities, and the duplicate becomes superseded."""
        return await self._retire(
            principal, memory_id, duplicate_id, MemoryEventAction.MERGED, copy_evidence=True
        )

    async def replace(
        self, principal: Principal, memory_id: uuid.UUID, outdated_id: uuid.UUID
    ) -> MemoryView:
        """Keep this memory over another that is out of date or wrong; the other becomes
        superseded and its evidence stays with it."""
        return await self._retire(
            principal, memory_id, outdated_id, MemoryEventAction.REPLACED, copy_evidence=False
        )

    async def delete(self, principal: Principal, memory_id: uuid.UUID) -> int:
        """Delete a memory and everything it replaced. Returns how many memories went."""
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            await owned_memory(memories, principal, memory_id)
            doomed = {memory_id}
            frontier = {memory_id}
            while frontier:
                frontier = await memories.replaced_by(frontier) - doomed
                doomed |= frontier
            # Everything a memory replaced is its owner's too; lock them before deleting.
            locked = await memories.lock_owned(doomed, principal.id)
            await memories.delete_memories(locked.keys())
            return len(locked)

    async def dismiss_suggestion(
        self, principal: Principal, first_id: uuid.UUID, second_id: uuid.UUID, kind: str
    ) -> None:
        """Stop suggesting that these two memories be reviewed together."""
        if first_id == second_id:
            raise InvalidMemoryChangeError("A suggestion is about two different memories.")
        now = self._clock()
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            locked = await memories.lock_owned({first_id, second_id}, principal.id)
            for memory_id, other_id in ((first_id, second_id), (second_id, first_id)):
                if memory_id not in locked:
                    raise RecordNotFoundError("Memory", str(memory_id))
                await memories.add_event(
                    memory_id,
                    MemoryEventAction.SUGGESTION_DISMISSED,
                    now=now,
                    details={"other_memory_id": str(other_id), "kind": kind},
                )

    # --- Helpers -----------------------------------------------------------------------

    async def _correct(
        self,
        memories: MemoryRepository,
        old: Memory,
        content: str,
        changes: MemoryChanges,
        now: datetime,
    ) -> Memory:
        sensitive = (
            changes.sensitive
            if changes.sensitive is not None
            else old.metadata_.get("sensitivity") == Sensitivity.SENSITIVE.value
        )
        state = old.metadata_.get("state", MemoryState.NOT_APPLICABLE.value)
        new = new_user_memory(
            owner_id=old.owner_id,
            memory_type=MemoryType(changes.memory_type or old.memory_type),
            content=content,
            metadata=MemoryMetadata(
                disposition=old.metadata_.get("disposition"),
                state=MemoryState(state),
                sensitivity=_sensitivity(sensitive),
            ).model_dump(mode="json"),
            now=now,
            observed_at=old.observed_at,
            supersedes_memory_id=old.id,
        )
        new.valid_from = old.valid_from
        new.valid_until = old.valid_until
        new.due_on = changes.due_on if changes.due_on_given else old.due_on
        new.remind_at = changes.remind_at if changes.remind_at_given else old.remind_at
        new.closed_at = old.closed_at
        new.close_reason = old.close_reason
        await memories.add_memories([new])
        await memories.copy_provenance(old.id, new.id, now=now)
        old.remind_at = None
        old.status = MemoryStatus.SUPERSEDED.value
        old.updated_at = now
        await memories.add_event(
            new.id,
            MemoryEventAction.CORRECTED,
            now=now,
            details={"previous_memory_id": str(old.id), "previous_content": old.content},
        )
        await memories.add_event(
            old.id,
            MemoryEventAction.SUPERSEDED,
            now=now,
            details={"by_memory_id": str(new.id), "reason": "corrected"},
        )
        return new

    async def _retire(
        self,
        principal: Principal,
        keep_id: uuid.UUID,
        other_id: uuid.UUID,
        action: MemoryEventAction,
        *,
        copy_evidence: bool,
    ) -> MemoryView:
        if keep_id == other_id:
            raise InvalidMemoryChangeError("Choose two different memories.")
        now = self._clock()
        async with transaction(self._session_factory) as session:
            memories = MemoryRepository(session)
            locked = await memories.lock_owned({keep_id, other_id}, principal.id)
            keep, other = locked.get(keep_id), locked.get(other_id)
            if keep is None:
                raise RecordNotFoundError("Memory", str(keep_id))
            if other is None:
                raise RecordNotFoundError("Memory", str(other_id))
            ensure_live(MemoryStatus(keep.status))
            ensure_live(MemoryStatus(other.status))
            if copy_evidence:
                await memories.copy_provenance(other.id, keep.id, now=now)
            await memories.add_relation(keep.id, other.id, RelationType.SUPERSEDES, now=now)
            other.status = MemoryStatus.SUPERSEDED.value
            other.updated_at = now
            keep.status = MemoryStatus.ACTIVE.value
            keep.updated_at = now
            await memories.add_event(
                keep.id,
                action,
                now=now,
                details={"memory_id": str(other.id), "content": other.content},
            )
            await memories.add_event(
                other.id,
                MemoryEventAction.SUPERSEDED,
                now=now,
                details={"by_memory_id": str(keep.id), "reason": action.value},
            )
            return MemoryView.of(keep)


def new_user_memory(
    *,
    owner_id: uuid.UUID | None,
    memory_type: MemoryType,
    content: str,
    metadata: dict[str, Any],
    now: datetime,
    observed_at: datetime | None = None,
    supersedes_memory_id: uuid.UUID | None = None,
) -> Memory:
    """An accepted memory written by the user."""
    return Memory(
        id=new_uuid(),
        memory_type=memory_type.value,
        content=content,
        normalized_content=normalize_for_matching(content),
        status=MemoryStatus.ACTIVE.value,
        observed_at=observed_at,
        supersedes_memory_id=supersedes_memory_id,
        metadata_=metadata,
        owner_id=owner_id,
        created_by=MemoryOrigin.USER.value,
        created_at=now,
        updated_at=now,
    )


def user_metadata(*, sensitive: bool) -> dict[str, Any]:
    """The metadata of a memory the user wrote from scratch."""
    return MemoryMetadata(
        state=MemoryState.NOT_APPLICABLE, sensitivity=_sensitivity(sensitive)
    ).model_dump(mode="json")


async def owned_memory(
    memories: MemoryRepository, principal: Principal, memory_id: uuid.UUID
) -> Memory:
    """One of the principal's memories, locked until the transaction ends."""
    memory = await memories.get_owned(memory_id, principal.id, for_update=True)
    if memory is None:
        raise RecordNotFoundError("Memory", str(memory_id))
    return memory


def clean_content(text: str) -> str:
    content = " ".join(text.split())
    if not content:
        raise InvalidMemoryChangeError("A memory needs some text.")
    if len(content) > MAX_CONTENT_CHARS:
        raise InvalidMemoryChangeError(
            f"A memory can be at most {MAX_CONTENT_CHARS} characters long."
        )
    return content


def _sensitivity(sensitive: bool) -> Sensitivity:
    return Sensitivity.SENSITIVE if sensitive else Sensitivity.NORMAL


_SCHEDULE_FIELDS: Final = frozenset({"due_on", "remind_at"})


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _apply_in_place(memory: Memory, changes: MemoryChanges) -> dict[str, dict[str, Any]]:
    """Apply kind, sensitivity, due date, and reminder changes; return what changed, as
    from and to."""
    edited: dict[str, dict[str, Any]] = {}
    if changes.due_on_given and changes.due_on != memory.due_on:
        edited["due_on"] = {"from": _iso(memory.due_on), "to": _iso(changes.due_on)}
        memory.due_on = changes.due_on
    if changes.remind_at_given and changes.remind_at != memory.remind_at:
        edited["remind_at"] = {"from": _iso(memory.remind_at), "to": _iso(changes.remind_at)}
        memory.remind_at = changes.remind_at
    if changes.memory_type is not None and changes.memory_type.value != memory.memory_type:
        edited["memory_type"] = {"from": memory.memory_type, "to": changes.memory_type.value}
        memory.memory_type = changes.memory_type.value
    if changes.sensitive is not None:
        was = memory.metadata_.get("sensitivity") == Sensitivity.SENSITIVE.value
        if was != changes.sensitive:
            edited["sensitive"] = {"from": was, "to": changes.sensitive}
            memory.metadata_ = {
                **memory.metadata_,
                "sensitivity": _sensitivity(changes.sensitive).value,
            }
    return edited
