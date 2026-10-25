"""Pipeline runner: executes processing runs and owns their state transitions.

One run moves through three short transactions:

1. Claim. The run goes from ``queued`` to ``running`` in one atomic statement.
2. Extract. The model is called with no transaction open, then the validated result is
   stored. A retry finds that result and skips the model call.
3. Materialize. Entity mentions, entities, memories, provenance, and the final status are
   written in one transaction, so a failure leaves nothing half-built.

Every write after the claim first locks the run row and checks that this worker still
owns the attempt. If a lease expired and another worker took over, the stale worker stops
without writing. Unique constraints on the derived records back this up at the database
level.

Raw messages are never touched here. Whatever happens to a run, its input is intact.
"""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import (
    ExtractionDisposition,
    ExtractionStatus,
    LlmCallOrigin,
    MemoryEntityRelation,
    PipelineStage,
    ProcessingStatus,
    RunEventType,
)
from app.domain.errors import ExtractionError, InvalidExtractionOutputError
from app.domain.normalization import locate_span
from app.domain.run_state import RetryPolicy, ensure_transition
from app.domain.versions import EXTRACTION_SCHEMA_VERSION, NORMALIZER_VERSION
from app.integrations.extraction.base import ExtractionResponse, Extractor
from app.integrations.llm_calls import LlmCallContext
from app.models.entity_mention import EntityMention
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from app.models.memory_entity import MemoryEntity
from app.models.memory_source import MemorySource
from app.models.processing_run import ProcessingRun
from app.models.raw_message import RawMessage
from app.repositories.entity_repository import EntityRepository
from app.repositories.memory_repository import MemoryRepository
from app.repositories.processing_run_repository import ProcessingRunRepository
from app.schemas.extraction import ExtractionPayload
from app.services.pacing import ALWAYS_ON, BackgroundPacer
from app.services.processing.extraction import ExtractionStage
from app.services.processing.memory_builder import MemoryBuilder, MemoryDraft
from app.services.processing.resolution import EntityResolver

logger = structlog.get_logger(__name__)

UNEXPECTED_ERROR_CODE = "UNEXPECTED_ERROR"
LEASE_EXPIRED_CODE = "LEASE_EXPIRED"

_ABSTAIN_DETAIL = (
    "The extractor abstained: the unit does not carry enough information for a reliable memory."
)


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    retry_policy: RetryPolicy
    lease: timedelta
    timezone_name: str


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """Where a run ended up after one execution by this worker."""

    run_id: uuid.UUID
    status: ProcessingStatus | None
    """``None`` when the run was not executed, or when another worker took it over."""


@dataclass(frozen=True, slots=True)
class _Claim:
    """Proof of ownership of one attempt of a run."""

    run_id: uuid.UUID
    attempt_number: int


@dataclass(slots=True)
class _Progress:
    """The stage being executed, kept so a failure can be attributed to it."""

    stage: PipelineStage = field(default=PipelineStage.NORMALIZE)


class _StaleClaimError(Exception):
    """This worker no longer owns the run. Another worker has taken it over."""


class PipelineRunner:
    """Executes processing runs.

    The runner is safe to share: it keeps no per-run state and opens a fresh session for
    every transaction. Several workers can run concurrently against the same database.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        extractor: Extractor | None,
        *,
        config: RunnerConfig,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._extractor = extractor
        self._config = config
        self._clock = clock
        self._builder = MemoryBuilder()
        self._extraction = (
            ExtractionStage(extractor, timezone_name=config.timezone_name)
            if extractor is not None
            else None
        )

    @property
    def can_process(self) -> bool:
        """False when no extractor is configured. Runs then stay queued, untouched."""
        return self._extraction is not None

    # --- Entry points --------------------------------------------------------------

    async def process_run(self, run_id: uuid.UUID) -> RunOutcome:
        """Execute one run if it is queued and due."""
        if not self.can_process:
            logger.info("processing_run_deferred", run_id=str(run_id), reason="no extractor")
            return RunOutcome(run_id, None)

        async with transaction(self._session_factory) as session:
            runs = ProcessingRunRepository(session)
            now = self._clock()
            run = await runs.claim(run_id, now=now)
            if run is None:
                return RunOutcome(run_id, None)
            await runs.add_event(run, RunEventType.CLAIMED, now=now)
            claim = _Claim(run.id, run.attempt_number)

        return RunOutcome(run_id, await self._execute(claim))

    async def process_runs(self, run_ids: Sequence[uuid.UUID]) -> list[RunOutcome]:
        """Execute the given runs one after another."""
        return [await self.process_run(run_id) for run_id in run_ids]

    async def next_due(self) -> datetime | None:
        """When a queued run becomes due (a retry's backoff ends) or a running one's
        lease expires."""
        async with self._session_factory() as session:
            runs = ProcessingRunRepository(session)
            queued = await runs.next_available_at()
            running = await runs.oldest_running_start()
        lease_ends = running + self._config.lease if running is not None else None
        return min((at for at in (queued, lease_ends) if at is not None), default=None)

    async def process_available(self, *, limit: int) -> list[RunOutcome]:
        """Recover expired leases, then execute up to ``limit`` due runs, oldest first."""
        if not self.can_process:
            logger.info("processing_deferred", reason="no extractor")
            return []

        await self.recover_expired_leases()
        outcomes: list[RunOutcome] = []
        for _ in range(limit):
            async with transaction(self._session_factory) as session:
                runs = ProcessingRunRepository(session)
                now = self._clock()
                run = await runs.claim_next(now=now)
                if run is None:
                    break
                await runs.add_event(run, RunEventType.CLAIMED, now=now)
                claim = _Claim(run.id, run.attempt_number)
            outcomes.append(RunOutcome(claim.run_id, await self._execute(claim)))
        return outcomes

    async def recover_expired_leases(self) -> int:
        """Release runs whose worker disappeared while they were ``running``.

        A released run is queued again if it has attempts left and fails otherwise.
        Returns how many runs were released.
        """
        policy = self._config.retry_policy
        async with transaction(self._session_factory) as session:
            runs = ProcessingRunRepository(session)
            now = self._clock()
            expired = await runs.lock_expired_leases(started_before=now - self._config.lease)
            for run in expired:
                await runs.add_event(
                    run,
                    RunEventType.LEASE_EXPIRED,
                    now=now,
                    error_code=LEASE_EXPIRED_CODE,
                    detail="The worker holding this run stopped responding.",
                )
                if policy.allows_retry_after(run.attempt_number):
                    ensure_transition(ProcessingStatus(run.status), ProcessingStatus.QUEUED)
                    run.status = ProcessingStatus.QUEUED.value
                    run.available_at = now
                else:
                    ensure_transition(ProcessingStatus(run.status), ProcessingStatus.FAILED)
                    run.status = ProcessingStatus.FAILED.value
                    run.finished_at = now
                    run.error_code = LEASE_EXPIRED_CODE
                    run.error_message = "The run timed out on its last allowed attempt."
                    await runs.add_event(
                        run, RunEventType.FAILED, now=now, error_code=LEASE_EXPIRED_CODE
                    )
            return len(expired)

    # --- Execution -----------------------------------------------------------------

    async def _execute(self, claim: _Claim) -> ProcessingStatus | None:
        progress = _Progress()
        try:
            extraction_result_id, payload, messages = await self._ensure_extraction(claim, progress)
            return await self._materialize(claim, extraction_result_id, payload, messages, progress)
        except _StaleClaimError:
            logger.warning("processing_run_claim_lost", run_id=str(claim.run_id))
            return None
        except ExtractionError as error:
            return await self._settle_failure(
                claim,
                progress.stage,
                error_code=error.code,
                detail=error.message,
                retryable=error.retryable,
                needs_review=isinstance(error, InvalidExtractionOutputError),
            )
        except Exception as error:
            # The engine hides bound parameters, so this traceback carries no message text.
            logger.exception(
                "processing_run_unexpected_error",
                run_id=str(claim.run_id),
                stage=progress.stage.value,
                error_type=type(error).__name__,
            )
            return await self._settle_failure(
                claim,
                progress.stage,
                error_code=UNEXPECTED_ERROR_CODE,
                detail=(
                    f"Unexpected {type(error).__name__} during the {progress.stage.value} stage."
                ),
                retryable=True,
                needs_review=False,
            )

    async def _ensure_extraction(
        self, claim: _Claim, progress: _Progress
    ) -> tuple[uuid.UUID, ExtractionPayload, list[RawMessage]]:
        """Return the run's extraction result, calling the extractor only if none is stored."""
        async with transaction(self._session_factory) as session:
            runs = ProcessingRunRepository(session)
            messages = await runs.messages(claim.run_id)
            stored = await runs.get_extraction_result(claim.run_id)
            if stored is not None:
                run = self._owned(await runs.get_for_update(claim.run_id), claim)
                await runs.add_event(
                    run,
                    RunEventType.EXTRACTION_REUSED,
                    now=self._clock(),
                    stage=PipelineStage.EXTRACT,
                )
                return stored.id, ExtractionPayload.model_validate(stored.payload), messages

        if self._extraction is None:  # pragma: no cover - entry points check can_process
            raise RuntimeError("No extractor is configured.")

        progress.stage = PipelineStage.EXTRACT
        stage_result = await self._extraction.run(
            messages,
            call_context=LlmCallContext(
                origin=LlmCallOrigin.PIPELINE,
                processing_run_id=claim.run_id,
                attempt_number=claim.attempt_number,
                # The extraction of a user's chat counts in that user's cost.
                user_id=_owner_of(messages),
            ),
        )
        response = stage_result.response
        payload = ExtractionPayload(
            normalizer_version=NORMALIZER_VERSION,
            message_ids=[message.id for message in messages],
            output=response.output,
        )

        async with transaction(self._session_factory) as session:
            runs = ProcessingRunRepository(session)
            run = self._owned(await runs.get_for_update(claim.run_id), claim)
            now = self._clock()
            abstained = response.output.disposition is ExtractionDisposition.ABSTAIN
            result = await runs.add_extraction_result(
                ExtractionResult(
                    id=new_uuid(),
                    processing_run_id=run.id,
                    schema_version=EXTRACTION_SCHEMA_VERSION,
                    extractor_version=self._extractor_version(),
                    model_name=response.model,
                    status=(
                        ExtractionStatus.NEEDS_REVIEW.value
                        if abstained
                        else ExtractionStatus.SUCCEEDED.value
                    ),
                    payload=payload.model_dump(mode="json"),
                    metadata_=_operational_metadata(response, stage_result.corrections),
                    created_at=now,
                )
            )
            await runs.add_event(
                run, RunEventType.EXTRACTION_STORED, now=now, stage=PipelineStage.EXTRACT
            )
            return result.id, payload, messages

    async def _materialize(
        self,
        claim: _Claim,
        extraction_result_id: uuid.UUID,
        payload: ExtractionPayload,
        messages: Sequence[RawMessage],
        progress: _Progress,
    ) -> ProcessingStatus:
        """Write everything the extraction result implies, and the run's final status."""
        output = payload.output
        async with transaction(self._session_factory) as session:
            runs = ProcessingRunRepository(session)
            run = self._owned(await runs.get_for_update(claim.run_id), claim)
            now = self._clock()

            if output.disposition is ExtractionDisposition.ABSTAIN:
                self._finish(run, ProcessingStatus.NEEDS_REVIEW, now)
                await runs.add_event(
                    run, RunEventType.NEEDS_REVIEW, now=now, detail=_ABSTAIN_DETAIL
                )
                return ProcessingStatus.NEEDS_REVIEW

            progress.stage = PipelineStage.RESOLVE
            entities = EntityRepository(session)
            owner_id = _owner_of(messages)
            resolver = EntityResolver(entities, owner_id=owner_id, clock=self._clock)
            mentions: list[EntityMention] = []
            resolved_entities: dict[int, uuid.UUID] = {}
            for ordinal, extracted in enumerate(output.entity_mentions):
                message = messages[extracted.message_index]
                resolution = await resolver.resolve(extracted.entity_type, extracted.mention_text)
                span = locate_span(message.content, extracted.mention_text)
                mentions.append(
                    EntityMention(
                        id=new_uuid(),
                        raw_message_id=message.id,
                        extraction_result_id=extraction_result_id,
                        ordinal=ordinal,
                        entity_type=extracted.entity_type.value,
                        mention_text=extracted.mention_text,
                        normalized_mention=resolution.normalized_mention,
                        start_offset=span[0] if span is not None else None,
                        end_offset=span[1] if span is not None else None,
                        resolution_status=resolution.status.value,
                        resolved_entity_id=resolution.entity_id,
                        confidence=round(extracted.confidence, 2),
                        created_at=now,
                    )
                )
                if resolution.entity_id is not None:
                    resolved_entities[ordinal] = resolution.entity_id
            await entities.add_mentions(mentions)

            progress.stage = PipelineStage.CONSTRUCT
            drafts = self._builder.build(output, messages, resolved_entities)

            progress.stage = PipelineStage.PERSIST
            await self._persist_memories(session, drafts, extraction_result_id, owner_id, now)

            self._finish(run, ProcessingStatus.SUCCEEDED, now)
            await runs.add_event(
                run,
                RunEventType.SUCCEEDED,
                now=now,
                detail=f"{len(drafts)} memories and {len(mentions)} entity mentions stored.",
            )
            return ProcessingStatus.SUCCEEDED

    async def _persist_memories(
        self,
        session: AsyncSession,
        drafts: Sequence[MemoryDraft],
        extraction_result_id: uuid.UUID,
        owner_id: uuid.UUID | None,
        now: datetime,
    ) -> None:
        repository = MemoryRepository(session)
        memories: list[Memory] = []
        sources: list[MemorySource] = []
        links: list[MemoryEntity] = []
        for draft in drafts:
            memory_id = new_uuid()
            memories.append(
                Memory(
                    id=memory_id,
                    memory_type=draft.memory_type,
                    content=draft.content,
                    normalized_content=draft.normalized_content,
                    status=draft.status.value,
                    confidence=draft.confidence,
                    observed_at=draft.observed_at,
                    due_on=draft.due_on,
                    origin_extraction_result_id=extraction_result_id,
                    origin_ordinal=draft.ordinal,
                    metadata_=draft.metadata,
                    owner_id=owner_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            sources.extend(
                MemorySource(
                    id=new_uuid(),
                    memory_id=memory_id,
                    raw_message_id=source.raw_message_id,
                    extraction_result_id=extraction_result_id,
                    evidence_text=source.evidence_text,
                    source_role=source.source_role.value,
                    created_at=now,
                )
                for source in draft.sources
            )
            links.extend(
                MemoryEntity(
                    memory_id=memory_id,
                    entity_id=entity_id,
                    relationship_type=MemoryEntityRelation.MENTIONS.value,
                    created_at=now,
                )
                for entity_id in draft.entity_ids
            )
        # Parents first: sources and links reference the memories.
        await repository.add_memories(memories)
        await repository.add_sources(sources)
        await repository.add_entity_links(links)

    async def _settle_failure(
        self,
        claim: _Claim,
        stage: PipelineStage,
        *,
        error_code: str,
        detail: str,
        retryable: bool,
        needs_review: bool,
    ) -> ProcessingStatus | None:
        """Record a failed attempt and decide what happens to the run next."""
        policy = self._config.retry_policy
        async with transaction(self._session_factory) as session:
            runs = ProcessingRunRepository(session)
            try:
                run = self._owned(await runs.get_for_update(claim.run_id), claim)
            except _StaleClaimError:
                return None
            now = self._clock()
            run.error_code = error_code
            run.error_message = detail

            if needs_review:
                self._finish(run, ProcessingStatus.NEEDS_REVIEW, now)
                event_type = RunEventType.NEEDS_REVIEW
                target = ProcessingStatus.NEEDS_REVIEW
            elif retryable and policy.allows_retry_after(run.attempt_number):
                ensure_transition(ProcessingStatus(run.status), ProcessingStatus.QUEUED)
                run.status = ProcessingStatus.QUEUED.value
                run.available_at = now + policy.delay_after(run.attempt_number)
                event_type = RunEventType.RETRY_SCHEDULED
                target = ProcessingStatus.QUEUED
            else:
                self._finish(run, ProcessingStatus.FAILED, now)
                event_type = RunEventType.FAILED
                target = ProcessingStatus.FAILED

            await runs.add_event(
                run, event_type, now=now, stage=stage, error_code=error_code, detail=detail
            )
            logger.warning(
                "processing_run_attempt_failed",
                run_id=str(run.id),
                attempt=run.attempt_number,
                stage=stage.value,
                error_code=error_code,
                next_status=target.value,
            )
            return target

    # --- Helpers -------------------------------------------------------------------

    @staticmethod
    def _owned(run: ProcessingRun | None, claim: _Claim) -> ProcessingRun:
        """Return the run if this worker still owns the claimed attempt."""
        if (
            run is None
            or run.status != ProcessingStatus.RUNNING.value
            or run.attempt_number != claim.attempt_number
        ):
            raise _StaleClaimError
        return run

    @staticmethod
    def _finish(run: ProcessingRun, status: ProcessingStatus, now: datetime) -> None:
        ensure_transition(ProcessingStatus(run.status), status)
        run.status = status.value
        run.finished_at = now

    def _extractor_version(self) -> str:
        if self._extractor is None:  # pragma: no cover - entry points check can_process
            raise RuntimeError("No extractor is configured.")
        return self._extractor.descriptor.version


def _operational_metadata(
    response: ExtractionResponse, corrections: Sequence[str]
) -> dict[str, Any]:
    """Facts about the provider call worth keeping. Never content, never reasoning.

    ``corrections`` lists what the system changed in the extractor's output, so a stored
    payload that differs from what the model returned is always explained.
    """
    metadata: dict[str, Any] = {}
    if corrections:
        metadata["corrections"] = list(corrections)
    if response.request_id is not None:
        metadata["request_id"] = response.request_id
    if response.usage is not None:
        metadata["usage"] = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_input_tokens": response.usage.cache_read_input_tokens,
            "cache_creation_input_tokens": response.usage.cache_creation_input_tokens,
        }
    return metadata


def _owner_of(messages: Sequence[RawMessage]) -> uuid.UUID | None:
    """The owner of a unit's messages. Ingestion gives every message of a unit the same
    owner; a unit that somehow mixes them is refused rather than attributed to one."""
    owners = {message.owner_id for message in messages}
    if len(owners) > 1:
        raise ValueError("A processing unit mixes messages of different owners.")
    return next(iter(owners), None)


class PipelineLoop:
    """Processes due runs every ``interval_seconds`` while the API runs: retries whose
    backoff has passed, runs whose worker vanished, and anything captured while no
    extractor was configured. Several processes may run it at once: each run is claimed
    in the database. When the database should sleep, the pacer spaces passes out, except
    while a full batch shows more work is waiting (``app.services.pacing``)."""

    def __init__(
        self,
        runner: PipelineRunner,
        *,
        interval_seconds: float,
        batch_size: int,
        pacer: BackgroundPacer = ALWAYS_ON,
    ) -> None:
        self._runner = runner
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._pacer = pacer
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="pipeline-loop")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def run_once(self) -> list[RunOutcome]:
        return await self._runner.process_available(limit=self._batch_size)

    async def _loop(self) -> None:
        while True:
            outcomes: list[RunOutcome] = []
            try:
                outcomes = await self.run_once()
                if outcomes:
                    logger.info("pipeline_pass", processed=len(outcomes))
            except Exception:
                # A failed pass must not end the loop; the next pass tries again.
                logger.exception("pipeline_pass_failed")
            next_due = await self._pacer.next_due(self._runner.next_due, loop="pipeline")
            await self._pacer.sleep(
                self._interval_seconds,
                next_due=next_due,
                busy=len(outcomes) >= self._batch_size,
            )
