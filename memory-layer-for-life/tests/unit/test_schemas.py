"""API schemas: what is accepted at the boundary, and what is refused."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.enums import EntityType, MemoryType, MessageSource
from app.schemas.common import Page, PageParams
from app.schemas.entity import EntityMentionCreate
from app.schemas.health import HealthResponse, ReadinessResponse
from app.schemas.ingestion import IngestBatchRequest, IngestUnitRequest
from app.schemas.memory import MemoryCreate
from app.schemas.memory_metadata import MemoryMetadata
from app.schemas.processing import ReplayRequest
from app.schemas.raw_message import RawMessageCreate


def test_health_response_valid() -> None:
    assert HealthResponse(status="alive", app_name="test", environment="test").status == "alive"


def test_readiness_response_valid() -> None:
    assert ReadinessResponse(status="ready", database="connected").details is None


# --- Raw messages ---------------------------------------------------------------------


def test_raw_message_create_valid() -> None:
    message = RawMessageCreate(
        source=MessageSource.API_INPUT,
        content="Hello",
        source_message_id="evt-1",
        source_created_at=datetime(2026, 1, 1, tzinfo=UTC),
        metadata={"device": "phone", "tags": ["a", 1]},
    )

    assert message.source is MessageSource.API_INPUT
    assert message.metadata == {"device": "phone", "tags": ["a", 1]}


def test_raw_message_content_is_kept_exactly() -> None:
    """Validation checks the content but never rewrites it: it is evidence."""
    assert RawMessageCreate(source=MessageSource.API_INPUT, content="  hi \n").content == "  hi \n"


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"content": ""}, id="empty content"),
        pytest.param({"content": " \n\t "}, id="blank content"),
        pytest.param({"source": "invalid_source"}, id="unknown source"),
        pytest.param({"source_message_id": ""}, id="empty source id"),
        pytest.param({"source_message_id": "x" * 256}, id="source id too long"),
        pytest.param(
            {"source_created_at": datetime(2026, 1, 1)},
            id="timestamp without timezone",
        ),
        pytest.param(
            {"metadata": {"when": datetime(2026, 1, 1, tzinfo=UTC)}}, id="non-JSON metadata"
        ),
        pytest.param({"surprise": 1}, id="unknown field"),
    ],
)
def test_raw_message_create_rejects(fields: dict[str, Any]) -> None:
    values: dict[str, Any] = {"source": MessageSource.API_INPUT, "content": "Hello", **fields}

    with pytest.raises(ValidationError):
        RawMessageCreate(**values)


# --- Ingestion ------------------------------------------------------------------------


def test_units_and_batches_need_content() -> None:
    message = {"source": "api_input", "content": "Hello"}

    assert len(IngestUnitRequest.model_validate({"messages": [message]}).messages) == 1
    assert len(IngestBatchRequest.model_validate({"units": [{"messages": [message]}]}).units) == 1
    with pytest.raises(ValidationError):
        IngestUnitRequest.model_validate({"messages": []})
    with pytest.raises(ValidationError):
        IngestBatchRequest.model_validate({"units": []})
    with pytest.raises(ValidationError):
        IngestUnitRequest.model_validate({"messages": [message], "extra": True})


# --- Replay ---------------------------------------------------------------------------


def test_replay_request_takes_exactly_one_selector() -> None:
    message_id, run_id = uuid.uuid4(), uuid.uuid4()

    assert ReplayRequest(raw_message_ids=[message_id]).limit == 100
    assert ReplayRequest(run_ids=[run_id]).run_ids == [run_id]
    assert ReplayRequest(all_units=True, limit=5).limit == 5

    for invalid in (
        {},
        {"all_units": False},
        {"raw_message_ids": [str(message_id)], "run_ids": [str(run_id)]},
        {"run_ids": [str(run_id)], "all_units": True},
        {"raw_message_ids": []},
        {"all_units": True, "limit": 0},
        {"all_units": True, "limit": 501},
    ):
        with pytest.raises(ValidationError):
            ReplayRequest.model_validate(invalid)


# --- Pagination -----------------------------------------------------------------------


def test_page_params_have_safe_bounds() -> None:
    assert (PageParams().limit, PageParams().offset) == (50, 0)
    for invalid in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        with pytest.raises(ValidationError):
            PageParams(**invalid)


def test_page_carries_items_and_totals() -> None:
    page = Page[int](items=[1, 2], total=10, limit=2, offset=4)

    assert page.model_dump() == {"items": [1, 2], "total": 10, "limit": 2, "offset": 4}


# --- Memories and entities ------------------------------------------------------------


def test_memory_create_valid() -> None:
    assert MemoryCreate(memory_type=MemoryType.SEMANTIC_FACT, content="Fact").content == "Fact"


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"memory_type": "INVALID_TYPE"}, id="unknown type"),
        pytest.param({"confidence": 1.5}, id="confidence out of range"),
        pytest.param({"content": ""}, id="empty content"),
        pytest.param({"extra": "forbidden"}, id="unknown field"),
    ],
)
def test_memory_create_rejects(fields: dict[str, Any]) -> None:
    values: dict[str, Any] = {"memory_type": MemoryType.SEMANTIC_FACT, "content": "Fact", **fields}

    with pytest.raises(ValidationError):
        MemoryCreate(**values)


def test_memory_metadata_is_a_strict_contract() -> None:
    metadata = MemoryMetadata.model_validate(
        {"disposition": "extract", "state": "open", "sensitivity": "normal"}
    )

    assert metadata.schema_version == "1.0"
    assert metadata.financial is None
    with pytest.raises(ValidationError):
        MemoryMetadata.model_validate(
            {"disposition": "extract", "state": "open", "sensitivity": "normal", "mood": "good"}
        )
    with pytest.raises(ValidationError):
        MemoryMetadata.model_validate(
            {"disposition": "extract", "state": "finished", "sensitivity": "normal"}
        )


def test_entity_mention_offsets() -> None:
    assert (
        EntityMentionCreate(entity_type=EntityType.PERSON, mention_text="Alice").start_offset
        is None
    )
    assert (
        EntityMentionCreate(
            entity_type=EntityType.PERSON, mention_text="Alice", start_offset=0, end_offset=5
        ).end_offset
        == 5
    )
    with pytest.raises(ValueError, match="both present or both absent"):
        EntityMentionCreate(entity_type=EntityType.PERSON, mention_text="Alice", start_offset=0)
    with pytest.raises(ValueError, match="greater than or equal to"):
        EntityMentionCreate(
            entity_type=EntityType.PERSON, mention_text="Alice", start_offset=5, end_offset=2
        )
