"""Translate service results into API response schemas.

Handlers stay thin: they call a service and hand the result to one of these functions.
"""

from app.schemas.common import Page
from app.schemas.ingestion import (
    IngestedMessageResponse,
    IngestedRunResponse,
    IngestUnitResponse,
)
from app.schemas.memory import (
    MemoryDetailResponse,
    MemoryEntityResponse,
    MemoryResponse,
    MemorySourceResponse,
)
from app.schemas.processing import (
    ExtractionSummaryResponse,
    ProcessingRunDetailResponse,
    ProcessingRunEventResponse,
    ProcessingRunResponse,
    ReplayOutcomeResponse,
)
from app.services.ingestion import IngestedUnit
from app.services.processing.replay import ReplayOutcome
from app.services.queries import (
    MemoryDetailView,
    MemoryView,
    PageResult,
    RunDetailView,
    RunView,
)


def to_ingest_unit_response(unit: IngestedUnit) -> IngestUnitResponse:
    return IngestUnitResponse(
        messages=[IngestedMessageResponse.model_validate(message) for message in unit.messages],
        processing_run=IngestedRunResponse.model_validate(unit.run),
    )


def to_run_response(run: RunView) -> ProcessingRunResponse:
    return ProcessingRunResponse.model_validate(run)


def to_run_page(
    page: PageResult[RunView], *, limit: int, offset: int
) -> Page[ProcessingRunResponse]:
    return Page[ProcessingRunResponse](
        items=[to_run_response(run) for run in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


def to_run_detail_response(detail: RunDetailView) -> ProcessingRunDetailResponse:
    return ProcessingRunDetailResponse(
        **to_run_response(detail.run).model_dump(),
        events=[ProcessingRunEventResponse.model_validate(event) for event in detail.events],
        extraction=(
            ExtractionSummaryResponse.model_validate(detail.extraction)
            if detail.extraction is not None
            else None
        ),
        memory_ids=list(detail.memory_ids),
    )


def to_replay_outcome_response(outcome: ReplayOutcome) -> ReplayOutcomeResponse:
    return ReplayOutcomeResponse(action=outcome.action, processing_run=to_run_response(outcome.run))


def to_memory_response(memory: MemoryView) -> MemoryResponse:
    return MemoryResponse.model_validate(memory)


def to_memory_page(
    page: PageResult[MemoryView], *, limit: int, offset: int
) -> Page[MemoryResponse]:
    return Page[MemoryResponse](
        items=[to_memory_response(memory) for memory in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


def to_memory_detail_response(detail: MemoryDetailView) -> MemoryDetailResponse:
    return MemoryDetailResponse(
        **to_memory_response(detail.memory).model_dump(),
        sources=[MemorySourceResponse.model_validate(source) for source in detail.sources],
        entities=[MemoryEntityResponse.model_validate(entity) for entity in detail.entities],
    )
