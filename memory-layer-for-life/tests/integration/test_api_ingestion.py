"""Ingestion endpoints: capture, validation, idempotent redelivery, error format."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.raw_message import RawMessage
from tests.integration.conftest import ApiHarness
from tests.support.extraction import evidence, extraction, memory

UNITS = "/api/v1/ingestion/units"
BATCHES = "/api/v1/ingestion/batches"


def message(content: str = "buy milk", **fields: Any) -> dict[str, Any]:
    return {"source": "manual_capture", "content": content, **fields}


async def _message_count(api: ApiHarness) -> int:
    async with api.container.session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(RawMessage)) or 0)


async def test_capture_is_accepted_and_processed(api: ApiHarness) -> None:
    api.extractor.use_script(
        extraction(memory("Buy milk", evidence_refs=[evidence(0, "buy milk")]))
    )

    response = await api.client.post(
        UNITS,
        json={
            "messages": [
                message(
                    source_message_id="note-1",
                    source_created_at="2026-10-01T09:30:00+05:30",
                    metadata={"device": "phone"},
                )
            ]
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"messages", "processing_run"}
    (stored,) = body["messages"]
    assert set(stored) == {"id", "source", "source_message_id", "ingested_at", "created"}
    assert stored["source"] == "manual_capture"
    assert stored["source_message_id"] == "note-1"
    assert stored["created"] is True
    run = body["processing_run"]
    assert set(run) == {"id", "status", "pipeline_version", "attempt_number", "created"}
    # The response reports the state at capture time. Processing follows the response.
    assert run["status"] == "queued"
    assert run["created"] is True

    detail = (await api.client.get(f"/api/v1/processing/runs/{run['id']}")).json()
    assert detail["status"] == "succeeded"
    assert detail["raw_message_ids"] == [stored["id"]]
    assert len(detail["memory_ids"]) == 1
    assert api.extractor.call_count == 1


async def test_redelivery_is_accepted_without_creating_anything(api: ApiHarness) -> None:
    payload = {"messages": [message(source_message_id="note-1")]}

    first = (await api.client.post(UNITS, json=payload)).json()
    second_response = await api.client.post(UNITS, json=payload)

    assert second_response.status_code == 202
    second = second_response.json()
    assert second["messages"][0]["id"] == first["messages"][0]["id"]
    assert second["messages"][0]["created"] is False
    assert second["processing_run"]["id"] == first["processing_run"]["id"]
    assert second["processing_run"]["created"] is False
    assert second["processing_run"]["status"] == "succeeded"
    assert await _message_count(api) == 1
    assert api.extractor.call_count == 1


async def test_changed_content_for_a_known_source_id_is_a_conflict(api: ApiHarness) -> None:
    await api.client.post(UNITS, json={"messages": [message(source_message_id="note-1")]})

    response = await api.client.post(
        UNITS, json={"messages": [message("buy oat milk", source_message_id="note-1")]}
    )

    assert response.status_code == 409
    body = response.json()
    assert set(body) == {"error_code", "message", "detail"}
    assert body["error_code"] == "SOURCE_CONTENT_CONFLICT"
    assert "buy oat milk" not in response.text
    assert await _message_count(api) == 1


async def test_a_unit_of_several_messages_is_one_run(api: ApiHarness) -> None:
    response = await api.client.post(
        UNITS, json={"messages": [message("229"), message("Ice cream")]}
    )

    assert response.status_code == 202
    body = response.json()
    assert len(body["messages"]) == 2
    (request,) = api.extractor.requests
    assert [item.text for item in request.messages] == ["229", "Ice cream"]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"messages": []}, id="no messages"),
        pytest.param({}, id="missing messages"),
        pytest.param({"messages": [message("   ")]}, id="blank content"),
        pytest.param({"messages": [message("")]}, id="empty content"),
        pytest.param({"messages": [{"content": "buy milk"}]}, id="missing source"),
        pytest.param({"messages": [message(source="carrier_pigeon")]}, id="unknown source"),
        pytest.param({"messages": [message(extra_field=1)]}, id="unknown field"),
        pytest.param(
            {"messages": [message(source_created_at="2026-10-01T09:30:00")]},
            id="timestamp without timezone",
        ),
        pytest.param({"messages": [message(source_message_id="")]}, id="empty source id"),
        pytest.param({"messages": [message()], "priority": "high"}, id="unknown top-level field"),
    ],
)
async def test_invalid_requests_are_rejected_in_the_standard_error_format(
    api: ApiHarness, payload: dict[str, Any]
) -> None:
    response = await api.client.post(UNITS, json=payload)

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error_code", "message", "detail"}
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["detail"]
    assert await _message_count(api) == 0
    assert api.extractor.call_count == 0


async def test_validation_errors_do_not_echo_submitted_content(api: ApiHarness) -> None:
    secret = "my private diary entry"

    response = await api.client.post(
        UNITS, json={"messages": [message(secret, source="carrier_pigeon")]}
    )

    assert response.status_code == 422
    assert secret not in response.text


async def test_a_unit_over_the_size_limit_is_rejected(api: ApiHarness) -> None:
    response = await api.client.post(UNITS, json={"messages": [message()] * 21})

    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_PROCESSING_UNIT"
    assert await _message_count(api) == 0


async def test_batch_capture_processes_every_unit(api: ApiHarness) -> None:
    response = await api.client.post(
        BATCHES,
        json={
            "units": [
                {"messages": [message("buy milk")]},
                {"messages": [message("print photos"), message("for the album")]},
            ]
        },
    )

    assert response.status_code == 202
    units = response.json()["units"]
    assert [len(unit["messages"]) for unit in units] == [1, 2]
    for unit in units:
        detail = (
            await api.client.get(f"/api/v1/processing/runs/{unit['processing_run']['id']}")
        ).json()
        assert detail["status"] == "succeeded"
    assert api.extractor.call_count == 2


async def test_a_batch_with_a_conflict_stores_nothing(api: ApiHarness) -> None:
    await api.client.post(UNITS, json={"messages": [message(source_message_id="note-1")]})

    response = await api.client.post(
        BATCHES,
        json={
            "units": [
                {"messages": [message("print photos", source_message_id="note-2")]},
                {"messages": [message("changed", source_message_id="note-1")]},
            ]
        },
    )

    assert response.status_code == 409
    assert await _message_count(api) == 1


async def test_without_a_provider_key_capture_still_works(
    api_without_extractor: AsyncClient,
) -> None:
    response = await api_without_extractor.post(UNITS, json={"messages": [message()]})

    assert response.status_code == 202
    run_id = response.json()["processing_run"]["id"]
    detail = (await api_without_extractor.get(f"/api/v1/processing/runs/{run_id}")).json()
    # Stored and waiting. Nothing was lost and nothing was attempted.
    assert detail["status"] == "queued"
    assert [event["event_type"] for event in detail["events"]] == ["queued"]
