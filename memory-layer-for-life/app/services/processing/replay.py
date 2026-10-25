"""Replay: make sure stored units have a run under the current pipeline configuration.

Replay is not a new capture. It never creates or changes a raw message, and it never
touches the output of earlier runs. For each selected unit it looks up the run that
belongs to the current processing identity and acts on what it finds:

* No such run: one is created and queued. This is how a new pipeline, prompt, model, or
  schema version reprocesses old input. Runs and memories of older versions stay as
  they are, so history is preserved. Their memories remain ``proposed``; choosing between
  versions is an explicit later step.
* A failed run: it is queued again.
* A run awaiting review with no stored extraction result: it is queued again, because the
  extractor's output was rejected and a new attempt can differ.
* Anything else is left unchanged. In particular a succeeded run is never executed again,
  so replaying the same version has no effect.

Replay is an operator tool and only ever selects the operator's own units. App users'
messages are processed when they are captured; reprocessing them would spend model calls
on their data and give them new memories nobody asked for.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.session import transaction
from app.domain.enums import ProcessingStatus, ReplayAction, RunEventType
from app.domain.identity import processing_idempotency_key
from app.domain.run_state import ensure_transition
from app.domain.versions import PipelineFingerprint
from app.repositories.processing_run_repository import ProcessingRunRepository, Unit
from app.services.queries import RunView


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    action: ReplayAction
    run: RunView


class ReplayService:
    """Owns its transaction: one call ensures runs for all selected units, or for none."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        fingerprint: PipelineFingerprint,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._fingerprint = fingerprint
        self._clock = clock

    async def replay(
        self,
        *,
        raw_message_ids: Sequence[uuid.UUID] | None = None,
        run_ids: Sequence[uuid.UUID] | None = None,
        limit: int,
    ) -> list[ReplayOutcome]:
        """Ensure a current run for every selected unit of the operator's.

        With ``raw_message_ids``, every unit containing one of the messages is selected.
        With ``run_ids``, the units of those runs. With neither, all of the operator's
        stored units. App users' units are never selected, even by id.
        """
        async with transaction(self._session_factory) as session:
            runs = ProcessingRunRepository(session)
            units = await runs.distinct_units(
                raw_message_ids=raw_message_ids, run_ids=run_ids, operator_only=True, limit=limit
            )
            return [await self._ensure_current_run(runs, unit) for unit in units]

    async def _ensure_current_run(self, runs: ProcessingRunRepository, unit: Unit) -> ReplayOutcome:
        now = self._clock()
        created_run, created = await runs.create_if_absent(
            idempotency_key=processing_idempotency_key(unit, self._fingerprint),
            raw_message_ids=unit,
            pipeline_version=self._fingerprint.pipeline_version,
            metadata={"pipeline": self._fingerprint.as_dict(), "origin": "replay"},
            now=now,
        )
        if created:
            await runs.add_event(
                created_run, RunEventType.QUEUED, now=now, detail="Created by replay."
            )
            return ReplayOutcome(ReplayAction.CREATED, RunView.of(created_run, unit))

        run = await runs.get_for_update(created_run.id)
        if run is None:  # pragma: no cover - the row was just read in this transaction
            raise RuntimeError("Processing run disappeared during replay.")
        status = ProcessingStatus(run.status)

        retryable = status is ProcessingStatus.FAILED or (
            status is ProcessingStatus.NEEDS_REVIEW
            and await runs.get_extraction_result(run.id) is None
        )
        if not retryable:
            return ReplayOutcome(ReplayAction.UNCHANGED, RunView.of(run, unit))

        ensure_transition(status, ProcessingStatus.QUEUED)
        run.status = ProcessingStatus.QUEUED.value
        run.available_at = now
        run.finished_at = None
        await runs.add_event(run, RunEventType.REQUEUED, now=now, detail="Requeued by replay.")
        return ReplayOutcome(ReplayAction.REQUEUED, RunView.of(run, unit))
