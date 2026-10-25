"""Capture of incoming messages.

Ingestion does two things and nothing else: it stores the raw messages, and it records
that the unit they form must be processed. It never calls a model. Storing the source
before any expensive work is what guarantees that a failed run cannot lose input.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.session import transaction
from app.domain.enums import ProcessingStatus, RunEventType
from app.domain.errors import InvalidProcessingUnitError, SourceContentConflictError
from app.domain.identity import content_sha256, processing_idempotency_key
from app.domain.versions import PipelineFingerprint
from app.repositories.message_repository import MessageRepository, NewRawMessage
from app.repositories.processing_run_repository import ProcessingRunRepository
from app.schemas.raw_message import RawMessageCreate


@dataclass(frozen=True, slots=True)
class IngestionLimits:
    max_unit_messages: int
    max_batch_units: int
    max_content_chars: int


@dataclass(frozen=True, slots=True)
class IngestedMessage:
    id: uuid.UUID
    source: str
    source_message_id: str | None
    ingested_at: datetime
    created: bool


@dataclass(frozen=True, slots=True)
class IngestedRun:
    id: uuid.UUID
    status: ProcessingStatus
    pipeline_version: str
    attempt_number: int
    created: bool


@dataclass(frozen=True, slots=True)
class IngestedUnit:
    messages: tuple[IngestedMessage, ...]
    run: IngestedRun


class IngestionService:
    """Stores processing units and queues their processing runs.

    The service owns its transaction: a call either stores every unit it was given and
    commits, or stores nothing. Callers can therefore start processing as soon as the
    call returns.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        fingerprint: PipelineFingerprint,
        limits: IngestionLimits,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._fingerprint = fingerprint
        self._limits = limits
        self._clock = clock

    async def ingest(
        self,
        units: Sequence[Sequence[RawMessageCreate]],
        *,
        owner_id: uuid.UUID | None = None,
    ) -> list[IngestedUnit]:
        """Store the units atomically and return what was created or matched.

        ``owner_id`` is the app user the messages belong to; None is the operator's own
        store. Every message of a call gets the same owner, so a unit never mixes owners.
        """
        self._check_limits(units)
        async with transaction(self._session_factory) as session:
            return [await self._ingest_unit(session, unit, owner_id) for unit in units]

    def _check_limits(self, units: Sequence[Sequence[RawMessageCreate]]) -> None:
        limits = self._limits
        if not units:
            raise InvalidProcessingUnitError("At least one unit is required.")
        if len(units) > limits.max_batch_units:
            raise InvalidProcessingUnitError(
                f"A batch can hold at most {limits.max_batch_units} units."
            )
        for unit in units:
            if not unit:
                raise InvalidProcessingUnitError("A processing unit needs at least one message.")
            if len(unit) > limits.max_unit_messages:
                raise InvalidProcessingUnitError(
                    f"A processing unit can hold at most {limits.max_unit_messages} messages."
                )
            if any(len(message.content) > limits.max_content_chars for message in unit):
                raise InvalidProcessingUnitError(
                    f"A message can be at most {limits.max_content_chars} characters long."
                )

    async def _ingest_unit(
        self,
        session: AsyncSession,
        unit: Sequence[RawMessageCreate],
        owner_id: uuid.UUID | None,
    ) -> IngestedUnit:
        messages = MessageRepository(session)
        runs = ProcessingRunRepository(session)
        now = self._clock()

        stored: list[IngestedMessage] = []
        for incoming in unit:
            new = NewRawMessage(
                source=incoming.source.value,
                content=incoming.content,
                content_sha256=content_sha256(incoming.content),
                source_message_id=incoming.source_message_id,
                source_created_at=(
                    incoming.source_created_at.astimezone(UTC)
                    if incoming.source_created_at is not None
                    else None
                ),
                metadata=dict(incoming.metadata),
                owner_id=owner_id,
            )
            if new.source_message_id is None:
                message, created = await messages.add(new, now=now), True
            else:
                message, created = await messages.add_if_absent(new, now=now)
                if not created and message.content_sha256 != new.content_sha256:
                    raise SourceContentConflictError(
                        f"Source '{new.source}' already delivered message "
                        f"'{new.source_message_id}' with different content. Stored evidence "
                        "is never overwritten."
                    )
                if not created and message.owner_id != owner_id:
                    raise SourceContentConflictError(
                        f"Source '{new.source}' already delivered message "
                        f"'{new.source_message_id}' for someone else."
                    )
            stored.append(
                IngestedMessage(
                    id=message.id,
                    source=message.source,
                    source_message_id=message.source_message_id,
                    ingested_at=message.ingested_at,
                    created=created,
                )
            )

        message_ids = [message.id for message in stored]
        # Also rejects a unit that names the same stored message twice.
        idempotency_key = processing_idempotency_key(message_ids, self._fingerprint)
        run, run_created = await runs.create_if_absent(
            idempotency_key=idempotency_key,
            raw_message_ids=message_ids,
            pipeline_version=self._fingerprint.pipeline_version,
            metadata={"pipeline": self._fingerprint.as_dict(), "origin": "ingestion"},
            now=now,
        )
        if run_created:
            await runs.add_event(run, RunEventType.QUEUED, now=now, detail="Unit captured.")

        return IngestedUnit(
            messages=tuple(stored),
            run=IngestedRun(
                id=run.id,
                status=ProcessingStatus(run.status),
                pipeline_version=run.pipeline_version,
                attempt_number=run.attempt_number,
                created=run_created,
            ),
        )
