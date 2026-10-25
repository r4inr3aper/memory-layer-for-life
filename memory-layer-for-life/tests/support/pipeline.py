"""A real pipeline wired to a scripted extractor and a controllable clock."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import MessageSource
from app.domain.run_state import RetryPolicy
from app.domain.versions import ExtractorDescriptor, PipelineFingerprint
from app.integrations.extraction.base import Extractor
from app.models.processing_run import ProcessingRun
from app.repositories.processing_run_repository import ProcessingRunRepository
from app.schemas.raw_message import RawMessageCreate
from app.services.ingestion import IngestedUnit, IngestionLimits, IngestionService
from app.services.processing.replay import ReplayService
from app.services.processing.runner import PipelineRunner, RunnerConfig, RunOutcome
from tests.support.extraction import DEFAULT_DESCRIPTOR

DEFAULT_START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
DEFAULT_LIMITS = IngestionLimits(max_unit_messages=20, max_batch_units=100, max_content_chars=20000)
DEFAULT_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=30, max_delay_seconds=900)
DEFAULT_LEASE = timedelta(minutes=10)


class FakeClock:
    """A clock that only moves when a test moves it."""

    def __init__(self, start: datetime = DEFAULT_START) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)


@dataclass
class PipelineHarness:
    session_factory: async_sessionmaker[AsyncSession]
    clock: FakeClock
    fingerprint: PipelineFingerprint
    ingestion: IngestionService
    runner: PipelineRunner
    replay: ReplayService

    async def ingest(
        self,
        *contents: str,
        source_ids: Sequence[str | None] | None = None,
        source: MessageSource = MessageSource.API_INPUT,
        sent_at: datetime | None = None,
    ) -> IngestedUnit:
        """Ingest one unit made of the given message texts."""
        ids = list(source_ids) if source_ids is not None else [None] * len(contents)
        (unit,) = await self.ingestion.ingest(
            [
                [
                    RawMessageCreate(
                        source=source,
                        content=content,
                        source_message_id=source_id,
                        source_created_at=sent_at,
                    )
                    for content, source_id in zip(contents, ids, strict=True)
                ]
            ]
        )
        return unit

    async def ingest_and_process(
        self, *contents: str, **options: Any
    ) -> tuple[IngestedUnit, RunOutcome]:
        unit = await self.ingest(*contents, **options)
        return unit, await self.runner.process_run(unit.run.id)

    async def get_run(self, run_id: uuid.UUID) -> ProcessingRun:
        async with self.session_factory() as session:
            run = await session.get(ProcessingRun, run_id)
            assert run is not None
            return run

    async def event_types(self, run_id: uuid.UUID) -> list[str]:
        async with self.session_factory() as session:
            return [
                event.event_type for event in await ProcessingRunRepository(session).events(run_id)
            ]

    async def rows(self, model: type[Any]) -> list[Any]:
        async with self.session_factory() as session:
            return list(await session.scalars(select(model)))

    async def count(self, model: type[Any]) -> int:
        async with self.session_factory() as session:
            return int(await session.scalar(select(func.count()).select_from(model)) or 0)


def build_harness(
    session_factory: async_sessionmaker[AsyncSession],
    extractor: Extractor | None,
    *,
    clock: FakeClock | None = None,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    lease: timedelta = DEFAULT_LEASE,
    timezone_name: str = "UTC",
    descriptor: ExtractorDescriptor | None = None,
) -> PipelineHarness:
    clock = clock or FakeClock()
    if descriptor is None:
        descriptor = extractor.descriptor if extractor is not None else DEFAULT_DESCRIPTOR
    fingerprint = PipelineFingerprint.for_extractor(descriptor)
    return PipelineHarness(
        session_factory=session_factory,
        clock=clock,
        fingerprint=fingerprint,
        ingestion=IngestionService(
            session_factory, fingerprint=fingerprint, limits=DEFAULT_LIMITS, clock=clock
        ),
        runner=PipelineRunner(
            session_factory,
            extractor,
            config=RunnerConfig(
                retry_policy=retry_policy, lease=lease, timezone_name=timezone_name
            ),
            clock=clock,
        ),
        replay=ReplayService(session_factory, fingerprint=fingerprint, clock=clock),
    )
