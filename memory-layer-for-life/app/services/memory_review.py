"""The review inbox: what needs its owner's eyes.

* Proposed memories: everything the pipeline saved and nobody has accepted yet.
* Suggestions: pairs of memories that look like duplicates or like they conflict
  (``app.domain.memory_review``), found by text and, when embeddings exist, by meaning.
  No model is asked. Dismissed pairs are not suggested again.
* Held-back messages: messages the pipeline would not turn into memories on its own (the
  extractor abstained, or its answer could not be used). The owner can save a memory from
  one, written by them and resting on that message, or dismiss it. Either way the run is
  marked ``reviewed`` and leaves the inbox; nothing about it is deleted.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import (
    MemoryEventAction,
    MemoryStatus,
    ProcessingStatus,
    RunEventType,
    SourceRole,
    SuggestionKind,
)
from app.domain.errors import RecordNotFoundError
from app.domain.memory_review import (
    LIVE_STATUSES,
    RELATED_MEANING_SIMILARITY,
    RELATED_TEXT_SIMILARITY,
    PairSignals,
    classify,
    numbers_in,
    strength,
)
from app.domain.principal import Principal
from app.domain.run_state import ensure_transition
from app.integrations.embeddings.base import EmbeddingSpace
from app.models.memory_source import MemorySource
from app.models.raw_message import RawMessage
from app.repositories.chat_repository import ChatRepository
from app.repositories.memory_repository import MemoryRepository
from app.repositories.memory_review_repository import MemoryReviewRepository
from app.repositories.processing_run_repository import ProcessingRunRepository
from app.services.memories import NewMemory, clean_content, new_user_memory, user_metadata
from app.services.queries import MemoryView, chat_thread_id

MAX_SUGGESTIONS: Final = 30
MAX_HELD_BACK: Final = 30
# Candidate pairs examined per signal before classifying.
_CANDIDATE_PAIRS: Final = 200
# Newest memories whose nearest neighbours by meaning are looked up.
_RECENT_FOR_MEANING: Final = 200


@dataclass(frozen=True, slots=True)
class SuggestionView:
    kind: SuggestionKind
    first: MemoryView
    second: MemoryView
    # How alike they are, 0 to 1: the stronger of text and meaning similarity.
    similarity: float
    shared_entities: int


@dataclass(frozen=True, slots=True)
class HeldBackMessageView:
    raw_message_id: uuid.UUID
    content: str
    sent_at: datetime | None
    # The chat thread it was sent in, while the thread exists.
    thread_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class HeldBackView:
    run_id: uuid.UUID
    held_at: datetime | None
    # True when the extractor found nothing reliable to remember; false when its answer
    # could not be used.
    unclear: bool
    messages: tuple[HeldBackMessageView, ...]


@dataclass(frozen=True, slots=True)
class FailedRunView:
    run_id: uuid.UUID
    failed_at: datetime | None
    error_code: str | None
    error_message: str | None
    messages: tuple[HeldBackMessageView, ...]


@dataclass(frozen=True, slots=True)
class ReviewInbox:
    proposed_count: int
    suggestions: tuple[SuggestionView, ...]
    held_back: tuple[HeldBackView, ...]
    held_back_count: int
    failed: tuple[FailedRunView, ...]
    failed_count: int


class MemoryReviewService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        space: EmbeddingSpace | None,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._space = space
        self._clock = clock

    async def inbox(self, principal: Principal) -> ReviewInbox:
        async with self._session_factory() as session:
            proposed = await MemoryRepository(session).count(principal.id, MemoryStatus.PROPOSED)
            suggestions = await self._suggestions(session, principal.id)
            held_back, held_back_count = await self._held_back(session, principal.id)
            failed, failed_count = await self._failed(session, principal.id)
        return ReviewInbox(
            proposed_count=proposed,
            suggestions=suggestions,
            held_back=held_back,
            held_back_count=held_back_count,
            failed=failed,
            failed_count=failed_count,
        )

    async def retry_failed(self, principal: Principal, run_id: uuid.UUID) -> None:
        """Queue one failed run again for this owner."""
        now = self._clock()
        async with transaction(self._session_factory) as session:
            runs = ProcessingRunRepository(session)
            run = await runs.get_failed(principal.id, run_id)
            if run is None:
                raise RecordNotFoundError("Failed run", str(run_id))
            ensure_transition(ProcessingStatus(run.status), ProcessingStatus.QUEUED)
            run.status = ProcessingStatus.QUEUED.value
            run.available_at = now
            run.finished_at = None
            run.error_code = None
            run.error_message = None
            await runs.add_event(
                run,
                RunEventType.REQUEUED,
                now=now,
                detail="Requeued by the owner from the review inbox.",
            )

    async def save_held_back(
        self, principal: Principal, run_id: uuid.UUID, new: NewMemory
    ) -> MemoryView:
        """Save a memory the user wrote from a held-back message. It rests on the run's
        messages, tied by the user rather than by an extraction."""
        content = clean_content(new.content)
        now = self._clock()
        async with transaction(self._session_factory) as session:
            runs = ProcessingRunRepository(session)
            run = await runs.get_held_back(principal.id, run_id)
            if run is None:
                raise RecordNotFoundError("Held-back message", str(run_id))
            messages = await runs.messages(run.id)
            memories = MemoryRepository(session)
            memory = new_user_memory(
                owner_id=principal.id,
                memory_type=new.memory_type,
                content=content,
                metadata=user_metadata(sensitive=new.sensitive),
                now=now,
                observed_at=max(
                    (sent for message in messages if (sent := message.source_created_at)),
                    default=None,
                ),
            )
            await memories.add_memories([memory])
            await memories.add_sources(
                [
                    MemorySource(
                        id=new_uuid(),
                        memory_id=memory.id,
                        raw_message_id=message.id,
                        extraction_result_id=None,
                        evidence_text=None,
                        source_role=SourceRole.SUPPORTING.value,
                        created_at=now,
                    )
                    for message in messages
                ]
            )
            await memories.add_event(
                memory.id,
                MemoryEventAction.CREATED,
                now=now,
                details={"processing_run_id": str(run.id)},
            )
            await runs.add_event(
                run, RunEventType.REVIEWED, now=now, detail="The owner saved a memory from it."
            )
            return MemoryView.of(memory)

    async def dismiss_held_back(self, principal: Principal, run_id: uuid.UUID) -> None:
        now = self._clock()
        async with transaction(self._session_factory) as session:
            runs = ProcessingRunRepository(session)
            run = await runs.get_held_back(principal.id, run_id)
            if run is None:
                raise RecordNotFoundError("Held-back message", str(run_id))
            await runs.add_event(
                run, RunEventType.REVIEWED, now=now, detail="The owner dismissed it."
            )

    # --- Helpers -----------------------------------------------------------------------

    async def _suggestions(
        self, session: AsyncSession, owner_id: uuid.UUID
    ) -> tuple[SuggestionView, ...]:
        review = MemoryReviewRepository(session)
        pairs = set(
            await review.alike_by_text(
                owner_id,
                LIVE_STATUSES,
                min_similarity=RELATED_TEXT_SIMILARITY,
                limit=_CANDIDATE_PAIRS,
            )
        )
        if self._space is not None:
            pairs.update(
                await review.alike_by_meaning(
                    owner_id,
                    LIVE_STATUSES,
                    space=self._space,
                    min_similarity=RELATED_MEANING_SIMILARITY,
                    recent=_RECENT_FOR_MEANING,
                )
            )
        memories = MemoryRepository(session)
        dismissed = await memories.dismissed_pairs(owner_id)
        pairs = {pair for pair in pairs if frozenset(pair) not in dismissed}
        rows = await review.pair_signals(sorted(pairs), space=self._space)
        loaded = {
            memory.id: memory
            for memory in await memories.get_many(
                {memory_id for pair in pairs for memory_id in pair}
            )
        }

        found: list[SuggestionView] = []
        for row in rows:
            first, second = loaded.get(row.first_id), loaded.get(row.second_id)
            if first is None or second is None:
                continue
            signals = PairSignals(
                same_type=row.same_type,
                shared_entities=row.shared_entities,
                identical_text=row.identical_text,
                text_similarity=row.text_similarity,
                meaning_similarity=row.meaning_similarity,
                numbers_a=numbers_in(first.content),
                numbers_b=numbers_in(second.content),
            )
            kind = classify(signals)
            if kind is None:
                continue
            # The older memory first, so "keep the newer one" reads naturally.
            older, newer = sorted(
                (first, second), key=lambda memory: (memory.created_at, memory.id)
            )
            found.append(
                SuggestionView(
                    kind=kind,
                    first=MemoryView.of(older),
                    second=MemoryView.of(newer),
                    similarity=round(strength(signals), 3),
                    shared_entities=row.shared_entities,
                )
            )
        found.sort(
            key=lambda suggestion: (
                suggestion.kind is not SuggestionKind.DUPLICATE,
                -suggestion.similarity,
                str(suggestion.first.id),
            )
        )
        return tuple(found[:MAX_SUGGESTIONS])

    async def _held_back(
        self, session: AsyncSession, owner_id: uuid.UUID
    ) -> tuple[tuple[HeldBackView, ...], int]:
        runs = ProcessingRunRepository(session)
        held, total = await runs.held_back(owner_id, limit=MAX_HELD_BACK)
        messages = await runs.messages_by_run([run.id for run in held])
        threads = {
            thread_id
            for unit in messages.values()
            for message in unit
            if (thread_id := chat_thread_id(message)) is not None
        }
        live_threads = await ChatRepository(session).existing_thread_ids(owner_id, threads)
        return (
            tuple(
                HeldBackView(
                    run_id=run.id,
                    held_at=run.finished_at,
                    # An abstention finishes the run without an error.
                    unclear=run.error_code is None,
                    messages=tuple(
                        _held_back_message(message, live_threads)
                        for message in messages.get(run.id, [])
                    ),
                )
                for run in held
            ),
            total,
        )

    async def _failed(
        self, session: AsyncSession, owner_id: uuid.UUID
    ) -> tuple[tuple[FailedRunView, ...], int]:
        runs = ProcessingRunRepository(session)
        failed, total = await runs.failed(owner_id, limit=MAX_HELD_BACK)
        messages = await runs.messages_by_run([run.id for run in failed])
        threads = {
            thread_id
            for unit in messages.values()
            for message in unit
            if (thread_id := chat_thread_id(message)) is not None
        }
        live_threads = await ChatRepository(session).existing_thread_ids(owner_id, threads)
        return (
            tuple(
                FailedRunView(
                    run_id=run.id,
                    failed_at=run.finished_at,
                    error_code=run.error_code,
                    error_message=run.error_message,
                    messages=tuple(
                        _held_back_message(message, live_threads)
                        for message in messages.get(run.id, [])
                    ),
                )
                for run in failed
            ),
            total,
        )


def _held_back_message(message: RawMessage, live_threads: set[uuid.UUID]) -> HeldBackMessageView:
    thread_id = chat_thread_id(message)
    return HeldBackMessageView(
        raw_message_id=message.id,
        content=message.content,
        sent_at=message.source_created_at,
        thread_id=thread_id if thread_id in live_threads else None,
    )
