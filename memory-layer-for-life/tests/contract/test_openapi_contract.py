"""The public HTTP contract, read from the generated OpenAPI document.

These tests pin what clients rely on: which operations exist, what they accept, and
which status codes and error shape they return.
"""

from typing import Any

import pytest

from app.main import create_app

PREFIX = "/api/v1"

OPERATIONS = {
    ("get", f"{PREFIX}/health/live"),
    ("get", f"{PREFIX}/health/ready"),
    ("post", f"{PREFIX}/ingestion/units"),
    ("post", f"{PREFIX}/ingestion/batches"),
    ("get", f"{PREFIX}/processing/runs"),
    ("get", f"{PREFIX}/processing/runs/{{run_id}}"),
    ("post", f"{PREFIX}/processing/replays"),
    ("get", f"{PREFIX}/memories"),
    ("get", f"{PREFIX}/memories/{{memory_id}}"),
    ("post", f"{PREFIX}/memories/search"),
    ("get", f"{PREFIX}/console/config"),
    ("post", f"{PREFIX}/console/connection-check"),
    ("get", f"{PREFIX}/console/pipeline-stats"),
    ("get", f"{PREFIX}/llm-calls"),
    ("get", f"{PREFIX}/llm-calls/usage"),
    ("get", f"{PREFIX}/llm-calls/{{call_id}}"),
    ("post", f"{PREFIX}/playground/extractions"),
    ("get", f"{PREFIX}/playground/extractions"),
    ("get", f"{PREFIX}/playground/extractions/{{run_id}}"),
    ("get", f"{PREFIX}/playground/contract"),
    ("get", f"{PREFIX}/evaluations"),
    ("post", f"{PREFIX}/evaluations"),
    ("get", f"{PREFIX}/evaluations/dataset"),
    ("get", f"{PREFIX}/evaluations/failing-cases"),
    ("get", f"{PREFIX}/evaluations/{{run_id}}"),
    ("get", f"{PREFIX}/evaluations/{{run_id}}/cases"),
    ("get", f"{PREFIX}/evaluations/{{run_id}}/cases/{{case_id}}"),
    ("post", f"{PREFIX}/evaluations/{{run_id}}/cancel"),
    ("get", f"{PREFIX}/reports/{{slug}}"),
    ("get", f"{PREFIX}/console/insights/usefulness"),
}

# The assistant app. Every one of these acts for a signed-in user.
APP_OPERATIONS = {
    ("get", f"{PREFIX}/me"),
    ("get", f"{PREFIX}/threads"),
    ("post", f"{PREFIX}/threads"),
    ("post", f"{PREFIX}/threads/main"),
    ("get", f"{PREFIX}/threads/{{thread_id}}"),
    ("delete", f"{PREFIX}/threads/{{thread_id}}"),
    ("get", f"{PREFIX}/threads/{{thread_id}}/messages"),
    ("post", f"{PREFIX}/threads/{{thread_id}}/messages"),
    ("post", f"{PREFIX}/threads/{{thread_id}}/messages/{{message_id}}/proposal/confirm"),
    ("post", f"{PREFIX}/threads/{{thread_id}}/messages/{{message_id}}/proposal/dismiss"),
    ("get", f"{PREFIX}/schedules"),
    ("get", f"{PREFIX}/schedules/{{schedule_id}}"),
    ("patch", f"{PREFIX}/schedules/{{schedule_id}}"),
    ("delete", f"{PREFIX}/schedules/{{schedule_id}}"),
    ("post", f"{PREFIX}/schedules/{{schedule_id}}/runs"),
    ("get", f"{PREFIX}/schedules/{{schedule_id}}/runs"),
    ("get", f"{PREFIX}/schedules/{{schedule_id}}/runs/{{run_id}}"),
    ("get", f"{PREFIX}/tools"),
    ("post", f"{PREFIX}/tools/{{slug}}/connect"),
    ("get", f"{PREFIX}/tools/{{slug}}/connection"),
    ("delete", f"{PREFIX}/tools/{{slug}}/connection"),
    ("patch", f"{PREFIX}/me"),
    ("delete", f"{PREFIX}/me"),
    ("get", f"{PREFIX}/me/usage"),
    ("get", f"{PREFIX}/me/usage/history"),
    ("get", f"{PREFIX}/me/memories"),
    ("post", f"{PREFIX}/me/memories"),
    ("post", f"{PREFIX}/me/memories/search"),
    ("get", f"{PREFIX}/me/memories/review"),
    ("post", f"{PREFIX}/me/memories/review/accept"),
    ("post", f"{PREFIX}/me/memories/review/dismiss"),
    ("post", f"{PREFIX}/me/memories/held-back/{{run_id}}/save"),
    ("post", f"{PREFIX}/me/memories/held-back/{{run_id}}/dismiss"),
    ("get", f"{PREFIX}/me/memories/{{memory_id}}"),
    ("patch", f"{PREFIX}/me/memories/{{memory_id}}"),
    ("delete", f"{PREFIX}/me/memories/{{memory_id}}"),
    ("post", f"{PREFIX}/me/memories/{{memory_id}}/accept"),
    ("post", f"{PREFIX}/me/memories/{{memory_id}}/retract"),
    ("post", f"{PREFIX}/me/memories/{{memory_id}}/restore"),
    ("post", f"{PREFIX}/me/memories/{{memory_id}}/merge"),
    ("post", f"{PREFIX}/me/memories/{{memory_id}}/replace"),
    ("post", f"{PREFIX}/me/memories/{{memory_id}}/complete"),
    ("post", f"{PREFIX}/me/memories/{{memory_id}}/drop"),
    ("post", f"{PREFIX}/me/memories/{{memory_id}}/reopen"),
    ("get", f"{PREFIX}/me/life"),
    ("get", f"{PREFIX}/me/life/brief"),
    ("post", f"{PREFIX}/me/messages/search"),
    ("get", f"{PREFIX}/me/insights"),
    ("post", f"{PREFIX}/me/insights/feedback"),
    ("post", f"{PREFIX}/me/imports/whatsapp"),
    ("post", f"{PREFIX}/me/imports/{{import_id}}/start"),
    ("get", f"{PREFIX}/me/imports"),
    ("get", f"{PREFIX}/me/imports/{{import_id}}"),
    ("post", f"{PREFIX}/me/memories/from-file"),
    ("get", f"{PREFIX}/me/sources"),
    ("patch", f"{PREFIX}/me/sources/{{app}}"),
    ("post", f"{PREFIX}/me/sources/{{app}}/sync"),
    ("get", f"{PREFIX}/me/people"),
    ("get", f"{PREFIX}/me/people/{{person_id}}"),
    ("patch", f"{PREFIX}/me/people/{{person_id}}"),
    ("post", f"{PREFIX}/me/people/{{person_id}}/merge"),
    ("get", f"{PREFIX}/me/export"),
    ("post", f"{PREFIX}/me/push-tokens"),
    ("delete", f"{PREFIX}/me/push-tokens/{{token}}"),
    ("post", f"{PREFIX}/feedback"),
    ("get", f"{PREFIX}/activity"),
    ("post", f"{PREFIX}/schedules"),
    ("delete", f"{PREFIX}/threads/{{thread_id}}/messages"),
}


@pytest.fixture(scope="module")
def openapi() -> dict[str, Any]:
    return create_app().openapi()


def operation(openapi: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    result: dict[str, Any] = openapi["paths"][path][method]
    return result


def response_schema_name(openapi: dict[str, Any], method: str, path: str, status: str) -> str:
    content = operation(openapi, method, path)["responses"][status]["content"]
    reference: str = content["application/json"]["schema"]["$ref"]
    return reference.rsplit("/", 1)[-1]


def query_parameters(openapi: dict[str, Any], path: str) -> dict[str, dict[str, Any]]:
    return {
        parameter["name"]: parameter
        for parameter in operation(openapi, "get", path).get("parameters", [])
        if parameter["in"] == "query"
    }


def test_exactly_the_documented_operations_exist(openapi: dict[str, Any]) -> None:
    published = {
        (method, path)
        for path, methods in openapi["paths"].items()
        for method in methods
        if method in {"get", "post", "put", "patch", "delete"}
    }

    assert published == OPERATIONS | APP_OPERATIONS


def test_the_memory_layer_cannot_update_or_delete(openapi: dict[str, Any]) -> None:
    """The memory layer exposes capture, inspection, and replay. Evidence is never mutated.

    The assistant app's own records (threads, schedules, connections) can change.
    """
    memory_paths = {path for _, path in OPERATIONS}
    methods = {
        method
        for path, methods in openapi["paths"].items()
        if path in memory_paths
        for method in methods
    }

    assert not methods & {"put", "patch", "delete"}


@pytest.mark.parametrize(("method", "path"), sorted(APP_OPERATIONS))
def test_app_operations_require_a_bearer_token(
    openapi: dict[str, Any], method: str, path: str
) -> None:
    assert operation(openapi, method, path)["security"] == [{"SupabaseAccessToken": []}]


OPERATOR_OPERATIONS = {
    (method, path) for method, path in OPERATIONS if not path.startswith(f"{PREFIX}/health/")
}


@pytest.mark.parametrize(("method", "path"), sorted(OPERATOR_OPERATIONS))
def test_operator_operations_document_the_operator_key(
    openapi: dict[str, Any], method: str, path: str
) -> None:
    assert operation(openapi, method, path)["security"] == [{"OperatorKey": []}]


@pytest.mark.parametrize("path", [f"{PREFIX}/health/live", f"{PREFIX}/health/ready"])
def test_health_checks_stay_open(openapi: dict[str, Any], path: str) -> None:
    assert "security" not in operation(openapi, "get", path)


def test_the_reply_streams_as_ndjson(openapi: dict[str, Any]) -> None:
    responses = operation(openapi, "post", f"{PREFIX}/threads/{{thread_id}}/messages")["responses"]

    assert "application/x-ndjson" in responses["200"]["content"]
    assert {"401", "404", "409", "422", "429", "503"} <= set(responses)


@pytest.mark.parametrize("path", [f"{PREFIX}/ingestion/units", f"{PREFIX}/ingestion/batches"])
def test_capture_is_accepted_asynchronously(openapi: dict[str, Any], path: str) -> None:
    responses = operation(openapi, "post", path)["responses"]

    assert set(responses) == {"202", "409", "422"}
    assert response_schema_name(openapi, "post", path, "409") == "ErrorResponse"
    assert response_schema_name(openapi, "post", path, "422") == "ErrorResponse"


def test_capture_schemas(openapi: dict[str, Any]) -> None:
    schemas = openapi["components"]["schemas"]

    assert response_schema_name(openapi, "post", f"{PREFIX}/ingestion/units", "202") == (
        "IngestUnitResponse"
    )
    message = schemas["RawMessageCreate"]
    assert set(message["required"]) == {"source", "content"}
    assert set(message["properties"]) == {
        "source",
        "content",
        "source_message_id",
        "source_created_at",
        "metadata",
    }
    assert message["additionalProperties"] is False
    assert schemas["IngestUnitRequest"]["additionalProperties"] is False
    assert schemas["IngestUnitRequest"]["properties"]["messages"]["minItems"] == 1
    assert set(schemas["IngestedMessageResponse"]["properties"]) == {
        "id",
        "source",
        "source_message_id",
        "ingested_at",
        "created",
    }


def test_run_endpoints(openapi: dict[str, Any]) -> None:
    listing = f"{PREFIX}/processing/runs"
    detail = f"{PREFIX}/processing/runs/{{run_id}}"

    parameters = query_parameters(openapi, listing)
    assert set(parameters) == {"status", "raw_message_id", "limit", "offset"}
    assert (parameters["limit"]["schema"]["minimum"], parameters["limit"]["schema"]["maximum"]) == (
        1,
        200,
    )
    assert set(operation(openapi, "get", detail)["responses"]) == {"200", "404", "422"}
    assert response_schema_name(openapi, "get", detail, "200") == "ProcessingRunDetailResponse"
    assert response_schema_name(openapi, "get", detail, "404") == "ErrorResponse"
    run_fields = set(openapi["components"]["schemas"]["ProcessingRunDetailResponse"]["properties"])
    assert {
        "status",
        "attempt_number",
        "raw_message_ids",
        "events",
        "extraction",
        "memory_ids",
    } <= (run_fields)


def test_replay_endpoint(openapi: dict[str, Any]) -> None:
    path = f"{PREFIX}/processing/replays"

    assert set(operation(openapi, "post", path)["responses"]) == {"202", "422"}
    request = openapi["components"]["schemas"]["ReplayRequest"]
    assert set(request["properties"]) == {"raw_message_ids", "run_ids", "all_units", "limit"}
    assert request["additionalProperties"] is False
    outcome = openapi["components"]["schemas"]["ReplayOutcomeResponse"]
    assert set(outcome["properties"]) == {"action", "processing_run"}


def test_memory_endpoints(openapi: dict[str, Any]) -> None:
    listing = f"{PREFIX}/memories"
    detail = f"{PREFIX}/memories/{{memory_id}}"

    assert set(query_parameters(openapi, listing)) == {
        "status",
        "memory_type",
        "processing_run_id",
        "limit",
        "offset",
    }
    assert set(operation(openapi, "get", detail)["responses"]) == {"200", "404", "422"}
    schemas = openapi["components"]["schemas"]
    assert {"sources", "entities", "metadata", "status"} <= set(
        schemas["MemoryDetailResponse"]["properties"]
    )
    # A memory's evidence shows the original message and the run that produced it.
    assert set(schemas["MemorySourceResponse"]["properties"]) == {
        "raw_message_id",
        "extraction_result_id",
        "processing_run_id",
        "source_role",
        "evidence_text",
        "source",
        "source_message_id",
        "source_created_at",
        "content",
    }


def test_memory_search_shapes(openapi: dict[str, Any]) -> None:
    schemas = openapi["components"]["schemas"]
    request = schemas["MemorySearchRequest"]
    # Strict, and the query travels in the body, never in the URL.
    assert request["additionalProperties"] is False
    assert set(request["required"]) == {"query"}
    for path in (f"{PREFIX}/memories/search", f"{PREFIX}/me/memories/search"):
        search = operation(openapi, "post", path)
        assert not [p for p in search.get("parameters", []) if p["in"] == "query"]
        assert {"200", "422"} <= set(search["responses"])
    assert {"items", "legs", "degraded", "embedding_space", "reranked"} <= set(
        schemas["MemorySearchResponse"]["properties"]
    )
    # Every result carries how it was found and the evidence it rests on.
    assert {"memory", "matched_by", "sources", "entities", "rank", "score"} <= set(
        schemas["MemorySearchHit"]["properties"]
    )


def test_error_shape(openapi: dict[str, Any]) -> None:
    error = openapi["components"]["schemas"]["ErrorResponse"]

    assert set(error["properties"]) == {"error_code", "message", "detail"}
    assert set(error["required"]) == {"error_code", "message"}


def test_collection_responses_are_paginated(openapi: dict[str, Any]) -> None:
    for path in (f"{PREFIX}/processing/runs", f"{PREFIX}/memories"):
        name = response_schema_name(openapi, "get", path, "200")
        page = openapi["components"]["schemas"][name]
        assert set(page["properties"]) == {"items", "total", "limit", "offset"}
        assert set(page["required"]) == {"items", "total", "limit", "offset"}
