"""Read side: views of processing runs and memories for inspection.

Views are plain immutable values copied out of the session, so they stay valid after
the transaction that produced them has ended.
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Self

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import (
    CloseReason,
    EntityType,
    ExtractionDisposition,
    ExtractionStatus,
    MemoryEntityRelation,
    MemoryOrigin,
    MemoryState,
    MemoryStatus,
    MemoryType,
    MessageSource,
    PipelineStage,
    ProcessingStatus,
    RunEventType,
    Sensitivity,
    SourceRole,
)
from app.domain.errors import RecordNotFoundError
from app.domain.memory_policy import display_title
from app.models.memory import Memory
from app.models.processing_run import ProcessingRun
from app.models.raw_message import RawMessage
from app.repositories.memory_repository import MemoryRepository
from app.repositories.processing_run_repository import ProcessingRunRepository


@dataclass(frozen=True, slots=True)
class RunView:
    id: uuid.UUID
    status: ProcessingStatus
    pipeline_version: str
    attempt_number: int
    raw_message_ids: tuple[uuid.UUID, ...]
    available_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime

    @classmethod
    def of(cls, run: ProcessingRun, raw_message_ids: Sequence[uuid.UUID]) -> Self:
        return cls(
            id=run.id,
            status=ProcessingStatus(run.status),
            pipeline_version=run.pipeline_version,
            attempt_number=run.attempt_number,
            raw_message_ids=tuple(raw_message_ids),
            available_at=run.available_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            error_code=run.error_code,
            error_message=run.error_message,
            created_at=run.created_at,
        )


@dataclass(frozen=True, slots=True)
class RunEventView:
    id: uuid.UUID
    attempt_number: int
    event_type: RunEventType
    stage: PipelineStage | None
    error_code: str | None
    detail: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ExtractionSummaryView:
    id: uuid.UUID
    schema_version: str
    extractor_version: str
    model_name: str | None
    status: ExtractionStatus
    disposition: ExtractionDisposition | None


@dataclass(frozen=True, slots=True)
class RunDetailView:
    run: RunView
    events: tuple[RunEventView, ...]
    extraction: ExtractionSummaryView | None
    memory_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class MemoryView:
    id: uuid.UUID
    memory_type: MemoryType
    content: str
    normalized_content: str | None
    status: MemoryStatus
    confidence: float | None
    valid_from: datetime | None
    valid_until: datetime | None
    observed_at: datetime | None
    supersedes_memory_id: uuid.UUID | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    created_by: MemoryOrigin
    # Shown to its owner, never given to a model.
    sensitive: bool
    # Life state: whether the thing described is open, planned, or done, when it is due,
    # when to remind, and when and why it was closed.
    state: MemoryState | None = None
    due_on: date | None = None
    remind_at: datetime | None = None
    closed_at: datetime | None = None
    close_reason: CloseReason | None = None
    # What a list shows (``app.domain.memory_policy.display_title``).
    title: str = ""

    @classmethod
    def of(cls, memory: Memory) -> Self:
        return cls(
            title=display_title(memory.content, memory.metadata_),
            id=memory.id,
            memory_type=MemoryType(memory.memory_type),
            content=memory.content,
            normalized_content=memory.normalized_content,
            status=MemoryStatus(memory.status),
            confidence=memory.confidence,
            valid_from=memory.valid_from,
            valid_until=memory.valid_until,
            observed_at=memory.observed_at,
            supersedes_memory_id=memory.supersedes_memory_id,
            metadata=dict(memory.metadata_),
            created_at=memory.created_at,
            updated_at=memory.updated_at,
            created_by=MemoryOrigin(memory.created_by),
            sensitive=memory.metadata_.get("sensitivity") == Sensitivity.SENSITIVE.value,
            state=_state(memory.metadata_.get("state")),
            due_on=memory.due_on,
            remind_at=memory.remind_at,
            closed_at=memory.closed_at,
            close_reason=CloseReason(memory.close_reason) if memory.close_reason else None,
        )


@dataclass(frozen=True, slots=True)
class MemorySourceView:
    raw_message_id: uuid.UUID
    # Empty when the user, not an extraction, tied the message to the memory.
    extraction_result_id: uuid.UUID | None
    processing_run_id: uuid.UUID | None
    source_role: SourceRole
    evidence_text: str | None
    source: MessageSource
    source_message_id: str | None
    source_created_at: datetime | None
    content: str
    # The chat thread the message was sent in, while the thread exists.
    thread_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class MemoryEntityView:
    entity_id: uuid.UUID
    entity_type: EntityType
    canonical_name: str
    relationship_type: MemoryEntityRelation


@dataclass(frozen=True, slots=True)
class MemoryDetailView:
    memory: MemoryView
    sources: tuple[MemorySourceView, ...]
    entities: tuple[MemoryEntityView, ...]


@dataclass(frozen=True, slots=True)
class PageResult[ItemT]:
    items: tuple[ItemT, ...]
    total: int


def _state(value: object) -> MemoryState | None:
    try:
        return MemoryState(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _extraction_disposition(payload: dict[str, Any]) -> ExtractionDisposition | None:
    """Read the disposition out of a stored extraction payload, tolerating old shapes."""
    output = payload.get("output")
    if not isinstance(output, dict):
        return None
    value = output.get("disposition")
    if not isinstance(value, str):
        return None
    try:
        return ExtractionDisposition(value)
    except ValueError:
        return None


class ProcessingQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self._runs = ProcessingRunRepository(session)
        self._memories = MemoryRepository(session)

    async def list_runs(
        self,
        *,
        status: ProcessingStatus | None,
        raw_message_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> PageResult[RunView]:
        runs, total = await self._runs.list_runs(
            status=status,
            raw_message_id=raw_message_id,
            operator_only=True,
            limit=limit,
            offset=offset,
        )
        units = await self._runs.message_ids_by_run([run.id for run in runs])
        return PageResult(
            items=tuple(RunView.of(run, units.get(run.id, ())) for run in runs), total=total
        )

    async def get_run(self, run_id: uuid.UUID) -> RunDetailView:
        run = await self._runs.get(run_id)
        if run is None or await self._runs.owner_of(run_id) is not None:
            raise RecordNotFoundError("Processing run", str(run_id))

        extraction = await self._runs.get_extraction_result(run_id)
        memory_ids = (
            await self._memories.ids_for_extraction_result(extraction.id)
            if extraction is not None
            else []
        )
        return RunDetailView(
            run=RunView.of(run, await self._runs.message_ids(run_id)),
            events=tuple(
                RunEventView(
                    id=event.id,
                    attempt_number=event.attempt_number,
                    event_type=RunEventType(event.event_type),
                    stage=PipelineStage(event.stage) if event.stage is not None else None,
                    error_code=event.error_code,
                    detail=event.detail,
                    created_at=event.created_at,
                )
                for event in await self._runs.events(run_id)
            ),
            extraction=(
                ExtractionSummaryView(
                    id=extraction.id,
                    schema_version=extraction.schema_version,
                    extractor_version=extraction.extractor_version,
                    model_name=extraction.model_name,
                    status=ExtractionStatus(extraction.status),
                    disposition=_extraction_disposition(extraction.payload),
                )
                if extraction is not None
                else None
            ),
            memory_ids=tuple(memory_ids),
        )


class MemoryQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self._memories = MemoryRepository(session)

    async def list_memories(
        self,
        *,
        status: MemoryStatus | None,
        memory_type: MemoryType | None,
        processing_run_id: uuid.UUID | None,
        limit: int,
        offset: int,
        owner_id: uuid.UUID | None = None,
    ) -> PageResult[MemoryView]:
        memories, total = await self._memories.list_memories(
            status=status,
            memory_type=memory_type,
            processing_run_id=processing_run_id,
            owner_id=owner_id,
            limit=limit,
            offset=offset,
        )
        return PageResult(items=tuple(MemoryView.of(memory) for memory in memories), total=total)

    async def get_memory(
        self, memory_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
    ) -> MemoryDetailView:
        """A memory with the evidence it rests on and the entities it involves."""
        memory = await self._memories.get_with_provenance(memory_id, owner_id=owner_id)
        if memory is None:
            raise RecordNotFoundError("Memory", str(memory_id))
        return memory_detail(memory)


def chat_thread_id(message: RawMessage) -> uuid.UUID | None:
    """The chat thread a captured message was sent in, when it says so."""
    value = message.metadata_.get("thread_id")
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def memory_detail(memory: Memory, *, live_threads: Collection[uuid.UUID] = ()) -> MemoryDetailView:
    """The views of a memory loaded with its provenance (``get_with_provenance``).
    ``live_threads`` are the chat threads that still exist: a source links to its thread
    only then."""
    sources = sorted(
        memory.sources,
        key=lambda source: (
            source.source_role != SourceRole.SUPPORTING.value,
            source.raw_message.source_created_at is None,
            source.raw_message.source_created_at,
            str(source.raw_message_id),
        ),
    )
    return MemoryDetailView(
        memory=MemoryView.of(memory),
        sources=tuple(
            MemorySourceView(
                raw_message_id=source.raw_message_id,
                extraction_result_id=source.extraction_result_id,
                processing_run_id=(
                    source.extraction_result.processing_run_id
                    if source.extraction_result is not None
                    else None
                ),
                source_role=SourceRole(source.source_role),
                evidence_text=source.evidence_text,
                source=MessageSource(source.raw_message.source),
                source_message_id=source.raw_message.source_message_id,
                source_created_at=source.raw_message.source_created_at,
                content=source.raw_message.content,
                thread_id=(
                    thread_id
                    if (thread_id := chat_thread_id(source.raw_message)) in live_threads
                    else None
                ),
            )
            for source in sources
        ),
        entities=tuple(
            MemoryEntityView(
                entity_id=link.entity_id,
                entity_type=EntityType(link.entity.entity_type),
                canonical_name=link.entity.canonical_name,
                relationship_type=MemoryEntityRelation(link.relationship_type),
            )
            for link in sorted(memory.memory_entities, key=lambda link: str(link.entity_id))
        ),
    )
