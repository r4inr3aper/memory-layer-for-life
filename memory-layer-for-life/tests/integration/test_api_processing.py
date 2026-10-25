"""Processing endpoints: inspecting runs, memories with evidence, and replay."""

import uuid
from typing import Any

import pytest

from app.domain.errors import PermanentExtractionError, TransientExtractionError
from tests.integration.conftest import ApiHarness
from tests.support.extraction import (
    abstention,
    evidence,
    extraction,
    financial,
    memory,
    mention,
)

UNITS = "/api/v1/ingestion/units"
RUNS = "/api/v1/processing/runs"
REPLAYS = "/api/v1/processing/replays"
MEMORIES = "/api/v1/memories"


async def capture(api: ApiHarness, *contents: str, **fields: Any) -> dict[str, Any]:
    response = await api.client.post(
        UNITS,
        json={
            "messages": [
                {"source": "manual_capture", "content": content, **fields} for content in contents
            ]
        },
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


# --- Runs -----------------------------------------------------------------------------


async def test_run_detail_shows_the_audit_log_and_the_extraction(api: ApiHarness) -> None:
    captured = await capture(api, "buy milk")

    response = await api.client.get(f"{RUNS}/{captured['processing_run']['id']}")

    assert response.status_code == 200
    detail = response.json()
    assert set(detail) == {
        "id",
        "status",
        "pipeline_version",
        "attempt_number",
        "raw_message_ids",
        "available_at",
        "started_at",
        "finished_at",
        "error_code",
        "error_message",
        "created_at",
        "events",
        "extraction",
        "memory_ids",
    }
    assert [event["event_type"] for event in detail["events"]] == [
        "queued",
        "claimed",
        "extraction_stored",
        "succeeded",
    ]
    assert detail["extraction"]["status"] == "succeeded"
    assert detail["extraction"]["disposition"] == "extract"
    assert detail["extraction"]["schema_version"] == "1.0"


async def test_a_failed_run_reports_a_sanitized_error(api: ApiHarness) -> None:
    api.extractor.use_script(PermanentExtractionError("The provider rejected the request."))
    captured = await capture(api, "something private")

    detail = (await api.client.get(f"{RUNS}/{captured['processing_run']['id']}")).json()

    assert detail["status"] == "failed"
    assert detail["error_code"] == "EXTRACTION_PERMANENT_FAILURE"
    assert detail["error_message"] == "The provider rejected the request."
    assert detail["extraction"] is None
    assert detail["memory_ids"] == []
    failure = detail["events"][-1]
    assert (failure["event_type"], failure["stage"]) == ("failed", "extract")
    assert "something private" not in str(detail)


async def test_runs_are_listed_newest_first_with_filters(api: ApiHarness) -> None:
    api.extractor.use_script(extraction(), abstention(), TransientExtractionError("busy"))
    succeeded = await capture(api, "buy milk")
    reviewed = await capture(api, "14 15")
    queued = await capture(api, "print photos")

    everything = (await api.client.get(RUNS)).json()
    assert everything["total"] == 3
    assert (everything["limit"], everything["offset"]) == (50, 0)
    assert [run["id"] for run in everything["items"]] == [
        queued["processing_run"]["id"],
        reviewed["processing_run"]["id"],
        succeeded["processing_run"]["id"],
    ]

    in_review = (await api.client.get(RUNS, params={"status": "needs_review"})).json()
    assert [run["id"] for run in in_review["items"]] == [reviewed["processing_run"]["id"]]
    assert in_review["total"] == 1

    by_message = (
        await api.client.get(RUNS, params={"raw_message_id": succeeded["messages"][0]["id"]})
    ).json()
    assert [run["id"] for run in by_message["items"]] == [succeeded["processing_run"]["id"]]

    page = (await api.client.get(RUNS, params={"limit": 1, "offset": 1})).json()
    assert page["total"] == 3
    assert [run["id"] for run in page["items"]] == [reviewed["processing_run"]["id"]]


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"status": "exploded"}, id="unknown status"),
        pytest.param({"limit": 0}, id="limit too small"),
        pytest.param({"limit": 201}, id="limit too large"),
        pytest.param({"offset": -1}, id="negative offset"),
        pytest.param({"raw_message_id": "not-a-uuid"}, id="malformed id"),
    ],
)
async def test_run_listing_validates_its_parameters(
    api: ApiHarness, params: dict[str, Any]
) -> None:
    response = await api.client.get(RUNS, params=params)

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


async def test_unknown_run_is_not_found(api: ApiHarness) -> None:
    response = await api.client.get(f"{RUNS}/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "NOT_FOUND"


# --- Memories -------------------------------------------------------------------------


async def test_memory_detail_traces_back_to_the_original_messages(api: ApiHarness) -> None:
    api.extractor.use_script(
        extraction(
            memory(
                "Petrol split with Harsh: 200",
                memory_type="financial_note",  # type: ignore[arg-type]
                evidence_refs=[evidence(0, "400/2 - petrol harsh")],
                mention_indexes=[0],
                financial=financial(200, component_amounts=[400], calculation="400 / 2"),
                ambiguity="It is unclear whose share this is.",
            ),
            mentions=[mention("harsh")],
        )
    )
    captured = await capture(
        api, "400/2 - petrol harsh", "next time I pay", source_created_at="2026-06-27T11:28:00Z"
    )
    run_id = captured["processing_run"]["id"]
    (memory_id,) = (await api.client.get(f"{RUNS}/{run_id}")).json()["memory_ids"]

    response = await api.client.get(f"{MEMORIES}/{memory_id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["content"] == "Petrol split with Harsh: 200"
    assert detail["memory_type"] == "financial_note"
    assert detail["status"] == "proposed"
    assert detail["observed_at"] == "2026-06-27T11:28:00Z"
    assert detail["metadata"]["financial"]["amount"] == 200
    assert detail["metadata"]["financial"]["currency"] is None
    assert detail["metadata"]["ambiguity"] == "It is unclear whose share this is."

    supporting, contextual = detail["sources"]
    assert supporting["source_role"] == "supporting"
    assert supporting["content"] == "400/2 - petrol harsh"
    assert supporting["evidence_text"] == "400/2 - petrol harsh"
    assert supporting["raw_message_id"] == captured["messages"][0]["id"]
    assert supporting["processing_run_id"] == run_id
    assert contextual["source_role"] == "contextual"
    assert contextual["content"] == "next time I pay"
    assert contextual["evidence_text"] is None

    (linked,) = detail["entities"]
    assert (linked["canonical_name"], linked["entity_type"]) == ("harsh", "person")
    assert linked["relationship_type"] == "mentions"


async def test_memories_can_be_listed_and_filtered(api: ApiHarness) -> None:
    api.extractor.use_script(
        extraction(memory("Buy milk")),
        extraction(memory("An AI life tracker", memory_type="idea")),  # type: ignore[arg-type]
    )
    first = await capture(api, "buy milk")
    await capture(api, "ai life tracking app")

    everything = (await api.client.get(MEMORIES)).json()
    assert everything["total"] == 2
    assert [item["content"] for item in everything["items"]] == ["An AI life tracker", "Buy milk"]

    ideas = (await api.client.get(MEMORIES, params={"memory_type": "idea"})).json()
    assert [item["content"] for item in ideas["items"]] == ["An AI life tracker"]

    proposed = (await api.client.get(MEMORIES, params={"status": "proposed"})).json()
    assert proposed["total"] == 2
    assert (await api.client.get(MEMORIES, params={"status": "active"})).json()["total"] == 0

    of_run = (
        await api.client.get(MEMORIES, params={"processing_run_id": first["processing_run"]["id"]})
    ).json()
    assert [item["content"] for item in of_run["items"]] == ["Buy milk"]


async def test_unknown_memory_is_not_found(api: ApiHarness) -> None:
    response = await api.client.get(f"{MEMORIES}/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "NOT_FOUND"


async def test_memory_listing_validates_its_parameters(api: ApiHarness) -> None:
    response = await api.client.get(MEMORIES, params={"memory_type": "rumour"})

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


# --- Replay ---------------------------------------------------------------------------


async def test_replaying_a_succeeded_unit_changes_nothing(api: ApiHarness) -> None:
    captured = await capture(api, "buy milk")

    response = await api.client.post(
        REPLAYS, json={"raw_message_ids": [captured["messages"][0]["id"]]}
    )

    assert response.status_code == 202
    (outcome,) = response.json()["outcomes"]
    assert outcome["action"] == "unchanged"
    assert outcome["processing_run"]["id"] == captured["processing_run"]["id"]
    assert api.extractor.call_count == 1
    assert (await api.client.get(MEMORIES)).json()["total"] == 1


async def test_replaying_a_failed_run_retries_it(api: ApiHarness) -> None:
    api.extractor.use_script(PermanentExtractionError("rejected"), extraction())
    captured = await capture(api, "buy milk")
    run_id = captured["processing_run"]["id"]

    response = await api.client.post(REPLAYS, json={"run_ids": [run_id]})

    assert response.status_code == 202
    (outcome,) = response.json()["outcomes"]
    assert outcome["action"] == "requeued"
    detail = (await api.client.get(f"{RUNS}/{run_id}")).json()
    assert detail["status"] == "succeeded"
    assert detail["attempt_number"] == 2
    assert len(detail["memory_ids"]) == 1


async def test_replaying_all_units_reports_each_unit_once(api: ApiHarness) -> None:
    await capture(api, "buy milk")
    await capture(api, "print photos")

    response = await api.client.post(REPLAYS, json={"all_units": True, "limit": 10})

    assert response.status_code == 202
    assert [outcome["action"] for outcome in response.json()["outcomes"]] == ["unchanged"] * 2


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="no selector"),
        pytest.param({"all_units": False}, id="selector switched off"),
        pytest.param({"raw_message_ids": []}, id="empty id list"),
        pytest.param(
            {"raw_message_ids": [str(uuid.uuid4())], "all_units": True}, id="two selectors"
        ),
        pytest.param({"run_ids": ["not-a-uuid"]}, id="malformed id"),
        pytest.param({"all_units": True, "limit": 0}, id="limit too small"),
        pytest.param({"all_units": True, "force": True}, id="unknown field"),
    ],
)
async def test_replay_requests_are_validated(api: ApiHarness, payload: dict[str, Any]) -> None:
    response = await api.client.post(REPLAYS, json=payload)

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


async def test_empty_collections_are_valid_pages(api: ApiHarness) -> None:
    for path in (RUNS, MEMORIES):
        response = await api.client.get(path)

        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
