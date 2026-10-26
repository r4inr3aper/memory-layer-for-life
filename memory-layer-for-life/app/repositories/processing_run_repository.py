import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, case, exists, func, select, update
from sqlalchemy.dialects.postgresql import aggregate_order_by, insert
from sqlalchemy.orm import aliased

from app.db.base import new_uuid
from app.domain.enums import MessageSource, PipelineStage, ProcessingStatus, RunEventType
from app.models.extraction_result import ExtractionResult
from app.models.processing_run import ProcessingRun
from app.models.processing_run_event import ProcessingRunEvent
from app.models.processing_run_message import ProcessingRunMessage
from app.models.raw_message import RawMessage
from app.repositories.base import BaseRepository

_IDEMPOTENCY_CONSTRAINT = "uq_processing_runs_idempotency_key"

Unit = tuple[uuid.UUID, ...]


def _operator_runs() -> ColumnElement[bool]:
    """Runs of the operator's own messages. A unit never mixes owners (ADR-037), so the
    run's first message decides."""
    return ProcessingRun.raw_message_id.in_(
        select(RawMessage.id).where(RawMessage.owner_id.is_(None))
    )


def _held_back_by(owner_id: uuid.UUID) -> list[ColumnElement[bool]]:
    """Runs of one owner's messages held back for review and not yet reviewed. Chat
    messages are left out: in a conversation, nothing to remember is the usual answer,
    not something to review (ADR-048)."""
    return [
        ProcessingRun.status == ProcessingStatus.NEEDS_REVIEW.value,
        ProcessingRun.raw_message_id.in_(
            select(RawMessage.id).where(
                RawMessage.owner_id == owner_id,
                RawMessage.source != MessageSource.APP_CHAT.value,
            )
        ),
        ~exists().where(
            ProcessingRunEvent.processing_run_id == ProcessingRun.id,
            ProcessingRunEvent.event_type == RunEventType.REVIEWED.value,
        ),
    ]


def _failed_by(owner_id: uuid.UUID) -> list[ColumnElement[bool]]:
    """Runs of one owner's messages that ended failed."""
    return [
        ProcessingRun.status == ProcessingStatus.FAILED.value,
        ProcessingRun.raw_message_id.in_(
            select(RawMessage.id).where(RawMessage.owner_id == owner_id)
        ),
    ]


class ProcessingRunRepository(BaseRepository):
    """Persistence of processing runs, their units, their audit log, and their results."""

    # --- Lookups -------------------------------------------------------------------

    async def get(self, run_id: uuid.UUID) -> ProcessingRun | None:
        return await self._session.get(ProcessingRun, run_id)

    async def get_for_update(self, run_id: uuid.UUID) -> ProcessingRun | None:
        """Load a run and hold a row lock on it until the transaction ends."""
        result = await self._session.scalars(
            select(ProcessingRun)
            .where(ProcessingRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.first()

    async def get_by_idempotency_key(self, idempotency_key: str) -> ProcessingRun | None:
        result = await self._session.scalars(
            select(ProcessingRun).where(ProcessingRun.idempotency_key == idempotency_key)
        )
        return result.first()

    async def list_runs(
        self,
        *,
        status: ProcessingStatus | None = None,
        raw_message_id: uuid.UUID | None = None,
        operator_only: bool = False,
        limit: int,
        offset: int,
    ) -> tuple[list[ProcessingRun], int]:
        """Page through runs, newest first. Returns the page and the total match count.
        ``operator_only`` leaves out runs of app users' messages."""
        conditions: list[ColumnElement[bool]] = []
        if operator_only:
            conditions.append(_operator_runs())
        if status is not None:
            conditions.append(ProcessingRun.status == status.value)
        if raw_message_id is not None:
            conditions.append(
                exists().where(
                    ProcessingRunMessage.processing_run_id == ProcessingRun.id,
                    ProcessingRunMessage.raw_message_id == raw_message_id,
                )
            )
        total = await self._session.scalar(
            select(func.count()).select_from(ProcessingRun).where(*conditions)
        )
        rows = await self._session.scalars(
            select(ProcessingRun)
            .where(*conditions)
            .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def held_back(
        self, owner_id: uuid.UUID, *, limit: int
    ) -> tuple[list[ProcessingRun], int]:
        """Runs of the owner's messages held back for review that the owner has not yet
        looked at (no ``reviewed`` event), newest first. Returns the page and the total."""
        conditions = _held_back_by(owner_id)
        total = await self._session.scalar(
            select(func.count()).select_from(ProcessingRun).where(*conditions)
        )
        rows = await self._session.scalars(
            select(ProcessingRun)
            .where(*conditions)
            .order_by(ProcessingRun.finished_at.desc().nulls_last(), ProcessingRun.id.desc())
            .limit(limit)
        )
        return list(rows), int(total or 0)

    async def get_held_back(self, owner_id: uuid.UUID, run_id: uuid.UUID) -> ProcessingRun | None:
        """One of the owner's held-back runs not yet reviewed, locked until the
        transaction ends."""
        result = await self._session.scalars(
            select(ProcessingRun)
            .where(ProcessingRun.id == run_id, *_held_back_by(owner_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.first()

    async def failed(self, owner_id: uuid.UUID, *, limit: int) -> tuple[list[ProcessingRun], int]:
        """Failed runs of one owner, newest first. Returns the page and total."""
        conditions = _failed_by(owner_id)
        total = await self._session.scalar(
            select(func.count()).select_from(ProcessingRun).where(*conditions)
        )
        rows = await self._session.scalars(
            select(ProcessingRun)
            .where(*conditions)
            .order_by(ProcessingRun.finished_at.desc().nulls_last(), ProcessingRun.id.desc())
            .limit(limit)
        )
        return list(rows), int(total or 0)

    async def get_failed(self, owner_id: uuid.UUID, run_id: uuid.UUID) -> ProcessingRun | None:
        """One failed run of the owner, locked for an update."""
        result = await self._session.scalars(
            select(ProcessingRun)
            .where(ProcessingRun.id == run_id, *_failed_by(owner_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.first()

    async def messages_by_run(
        self, run_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[RawMessage]]:
        """Each run's raw messages, in processing order."""
        if not run_ids:
            return {}
        rows = await self._session.execute(
            select(ProcessingRunMessage.processing_run_id, RawMessage)
            .join(RawMessage, RawMessage.id == ProcessingRunMessage.raw_message_id)
            .where(ProcessingRunMessage.processing_run_id.in_(run_ids))
            .order_by(ProcessingRunMessage.processing_run_id, ProcessingRunMessage.position)
        )
        messages: dict[uuid.UUID, list[RawMessage]] = {}
        for run_id, message in rows:
            messages.setdefault(run_id, []).append(message)
        return messages

    # --- Units ---------------------------------------------------------------------

    async def message_ids(self, run_id: uuid.UUID) -> list[uuid.UUID]:
        rows = await self._session.scalars(
            select(ProcessingRunMessage.raw_message_id)
            .where(ProcessingRunMessage.processing_run_id == run_id)
            .order_by(ProcessingRunMessage.position)
        )
        return list(rows)

    async def message_ids_by_run(self, run_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Unit]:
        """Ordered message ids of several runs in one query."""
        if not run_ids:
            return {}
        rows = await self._session.execute(
            select(
                ProcessingRunMessage.processing_run_id,
                func.array_agg(
                    aggregate_order_by(
                        ProcessingRunMessage.raw_message_id, ProcessingRunMessage.position
                    )
                ),
            )
            .where(ProcessingRunMessage.processing_run_id.in_(run_ids))
            .group_by(ProcessingRunMessage.processing_run_id)
        )
        return {run_id: tuple(message_ids) for run_id, message_ids in rows}

    async def owner_of(self, run_id: uuid.UUID) -> uuid.UUID | None:
        """The app user a run's messages belong to; None for the operator's own."""
        owner: uuid.UUID | None = await self._session.scalar(
            select(RawMessage.owner_id)
            .join(ProcessingRun, ProcessingRun.raw_message_id == RawMessage.id)
            .where(ProcessingRun.id == run_id)
        )
        return owner

    async def messages(self, run_id: uuid.UUID) -> list[RawMessage]:
        """The raw messages of a run's unit, in processing order."""
        rows = await self._session.scalars(
            select(RawMessage)
            .join(ProcessingRunMessage, ProcessingRunMessage.raw_message_id == RawMessage.id)
            .where(ProcessingRunMessage.processing_run_id == run_id)
            .order_by(ProcessingRunMessage.position)
        )
        return list(rows)

    async def distinct_units(
        self,
        *,
        raw_message_ids: Sequence[uuid.UUID] | None = None,
        run_ids: Sequence[uuid.UUID] | None = None,
        operator_only: bool = False,
        limit: int,
    ) -> list[Unit]:
        """Distinct units among the selected runs, oldest first.

        With ``raw_message_ids``, every unit that contains one of the messages is
        selected. With ``run_ids``, the units of those runs. With neither, all units.
        ``operator_only`` leaves out app users' units. A unit processed under several
        pipeline versions is returned once.
        """
        unit = func.array_agg(
            aggregate_order_by(ProcessingRunMessage.raw_message_id, ProcessingRunMessage.position)
        )
        statement = (
            select(unit)
            .join(ProcessingRun, ProcessingRun.id == ProcessingRunMessage.processing_run_id)
            .group_by(ProcessingRun.id, ProcessingRun.created_at)
            .order_by(ProcessingRun.created_at, ProcessingRun.id)
        )
        if operator_only:
            statement = statement.where(_operator_runs())
        if run_ids is not None:
            statement = statement.where(ProcessingRun.id.in_(run_ids))
        if raw_message_ids is not None:
            # A separate alias: the outer query aggregates all members of the run, while
            # this condition only asks whether one of them is a selected message.
            member = aliased(ProcessingRunMessage)
            statement = statement.where(
                exists().where(
                    member.processing_run_id == ProcessingRun.id,
                    member.raw_message_id.in_(raw_message_ids),
                )
            )

        units: list[Unit] = []
        seen: set[Unit] = set()
        stream = await self._session.stream(statement)
        async for (message_ids,) in stream:
            candidate: Unit = tuple(message_ids)
            if candidate in seen:
                continue
            seen.add(candidate)
            units.append(candidate)
            if len(units) >= limit:
                break
        await stream.close()
        return units

    # --- Creation and claiming -----------------------------------------------------

    async def create_if_absent(
        self,
        *,
        idempotency_key: str,
        raw_message_ids: Sequence[uuid.UUID],
        pipeline_version: str,
        metadata: dict[str, Any],
        now: datetime,
    ) -> tuple[ProcessingRun, bool]:
        """Create the run for a processing identity unless it already exists.

        Returns the run and whether this call created it. The unique constraint on
        ``idempotency_key`` decides, so concurrent callers cannot create two runs.
        """
        statement = (
            insert(ProcessingRun)
            .values(
                id=new_uuid(),
                raw_message_id=raw_message_ids[0],
                pipeline_version=pipeline_version,
                status=ProcessingStatus.QUEUED.value,
                attempt_number=1,
                idempotency_key=idempotency_key,
                available_at=now,
                metadata_=metadata,
                created_at=now,
            )
            .on_conflict_do_nothing(constraint=_IDEMPOTENCY_CONSTRAINT)
            .returning(ProcessingRun.id)
        )
        inserted_id = (await self._session.execute(statement)).scalar_one_or_none()
        if inserted_id is None:
            existing = await self.get_by_idempotency_key(idempotency_key)
            if existing is None:  # pragma: no cover - guarded by the unique constraint
                raise RuntimeError("Processing run conflict reported, but no row was found.")
            return existing, False

        self._session.add_all(
            ProcessingRunMessage(
                processing_run_id=inserted_id,
                raw_message_id=message_id,
                position=position,
                created_at=now,
            )
            for position, message_id in enumerate(raw_message_ids)
        )
        await self._session.flush()
        run = await self._session.get(ProcessingRun, inserted_id)
        if run is None:  # pragma: no cover - the row was inserted in this transaction
            raise RuntimeError("Inserted processing run could not be loaded.")
        return run, True

    async def claim(self, run_id: uuid.UUID, *, now: datetime) -> ProcessingRun | None:
        """Atomically move a queued, due run to ``running``.

        Returns ``None`` when the run is not queued or not yet due, which is also what a
        second concurrent claimer sees. The first execution keeps attempt number 1; every
        later claim increments it.
        """
        result = await self._session.scalars(
            update(ProcessingRun)
            .where(
                ProcessingRun.id == run_id,
                ProcessingRun.status == ProcessingStatus.QUEUED.value,
                ProcessingRun.available_at <= now,
            )
            .values(
                status=ProcessingStatus.RUNNING.value,
                attempt_number=case(
                    (ProcessingRun.started_at.is_(None), ProcessingRun.attempt_number),
                    else_=ProcessingRun.attempt_number + 1,
                ),
                started_at=now,
                finished_at=None,
                error_code=None,
                error_message=None,
            )
            .returning(ProcessingRun)
            .execution_options(populate_existing=True)
        )
        return result.first()

    async def next_available_at(self) -> datetime | None:
        """When the earliest queued run becomes due (a retry waits out its backoff)."""
        result: datetime | None = await self._session.scalar(
            select(func.min(ProcessingRun.available_at)).where(
                ProcessingRun.status == ProcessingStatus.QUEUED.value
            )
        )
        return result

    async def oldest_running_start(self) -> datetime | None:
        """When the longest-running run started; its lease expires a lease after that."""
        result: datetime | None = await self._session.scalar(
            select(func.min(ProcessingRun.started_at)).where(
                ProcessingRun.status == ProcessingStatus.RUNNING.value
            )
        )
        return result

    async def claim_next(self, *, now: datetime) -> ProcessingRun | None:
        """Claim the oldest due run, skipping rows another worker is claiming."""
        run_id = await self._session.scalar(
            select(ProcessingRun.id)
            .where(
                ProcessingRun.status == ProcessingStatus.QUEUED.value,
                ProcessingRun.available_at <= now,
            )
            .order_by(ProcessingRun.available_at, ProcessingRun.created_at, ProcessingRun.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if run_id is None:
            return None
        return await self.claim(run_id, now=now)

    async def lock_expired_leases(self, *, started_before: datetime) -> list[ProcessingRun]:
        """Lock runs that have been ``running`` since before the cutoff."""
        rows = await self._session.scalars(
            select(ProcessingRun)
            .where(
                ProcessingRun.status == ProcessingStatus.RUNNING.value,
                ProcessingRun.started_at < started_before,
            )
            .order_by(ProcessingRun.started_at)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        return list(rows)

    # --- Audit log -----------------------------------------------------------------

    async def add_event(
        self,
        run: ProcessingRun,
        event_type: RunEventType,
        *,
        now: datetime,
        stage: PipelineStage | None = None,
        error_code: str | None = None,
        detail: str | None = None,
    ) -> ProcessingRunEvent:
        event = ProcessingRunEvent(
            id=new_uuid(),
            processing_run_id=run.id,
            attempt_number=run.attempt_number,
            event_type=event_type.value,
            stage=stage.value if stage is not None else None,
            error_code=error_code,
            detail=detail,
            created_at=now,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def events(self, run_id: uuid.UUID) -> list[ProcessingRunEvent]:
        """Events in the order they were written. Ids are time-ordered and break ties."""
        rows = await self._session.scalars(
            select(ProcessingRunEvent)
            .where(ProcessingRunEvent.processing_run_id == run_id)
            .order_by(ProcessingRunEvent.created_at, ProcessingRunEvent.id)
        )
        return list(rows)

    # --- Extraction results --------------------------------------------------------

    async def get_extraction_result(self, run_id: uuid.UUID) -> ExtractionResult | None:
        result = await self._session.scalars(
            select(ExtractionResult).where(ExtractionResult.processing_run_id == run_id)
        )
        return result.first()

    async def add_extraction_result(self, result: ExtractionResult) -> ExtractionResult:
        self._session.add(result)
        await self._session.flush()
        return result
