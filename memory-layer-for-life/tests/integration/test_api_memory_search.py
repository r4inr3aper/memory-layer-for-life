"""Memory search over HTTP, and Cooper's search_memories tool in a real chat turn.

The app's search (``POST /me/memories/search``) is the signed-in user's own store; the
console's (``POST /memories/search``) is the operator's. Memories are made by the real
pipeline around a scripted extractor; the embedding provider is a deterministic fake.
"""

import uuid
from typing import Any

import pytest

from app.domain.enums import LlmCallOrigin, MessageSource
from app.domain.errors import IntegrationError
from app.domain.principal import Principal
from app.integrations.assistant.base import ToolResults
from app.integrations.embeddings.base import EmbeddingInputType
from app.schemas.extraction import ExtractionOutput
from app.schemas.raw_message import RawMessageCreate
from tests.integration.conftest import AssistantHarness, AssistantHarnessFactory
from tests.support.app_api import API, main_thread, stream
from tests.support.assistant import call, new_principal, say
from tests.support.embeddings import FakeEmbedder
from tests.support.retrieval import TEST_MIN_SIMILARITY, fact

SEARCH = f"{API}/me/memories/search"
CONSOLE_SEARCH = f"{API}/memories/search"

SISTER_MESSAGE = "My sister Priya lives in Pune"
SISTER = "The user's sister Priya lives in Pune."


async def signed_in(
    harness: AssistantHarness, name: str = "Ada"
) -> tuple[Principal, dict[str, str]]:
    principal = new_principal(name)
    headers = harness.sign_in(principal)
    # Any signed-in request creates the user's row, which their memories reference.
    response = await harness.client.get(f"{API}/me", headers=headers)
    assert response.status_code == 200, response.text
    return principal, headers


async def seed(
    harness: AssistantHarness,
    owner: uuid.UUID | None,
    message: str = SISTER_MESSAGE,
    output: ExtractionOutput | None = None,
) -> None:
    """Capture a message into the owner's store and run the pipeline on it."""
    harness.extractor.use_script(output or fact(SISTER, SISTER_MESSAGE, "Priya"))
    [unit] = await harness.container.ingestion_service.ingest(
        [[RawMessageCreate(source=MessageSource.API_INPUT, content=message)]], owner_id=owner
    )
    await harness.container.pipeline_runner.process_runs([unit.run.id])


async def search(
    harness: AssistantHarness, body: dict[str, Any], headers: dict[str, str] | None = None
) -> dict[str, Any]:
    response = await harness.client.post(
        SEARCH if headers else CONSOLE_SEARCH, json=body, headers=headers
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def contents(body: dict[str, Any]) -> list[str]:
    return [hit["memory"]["content"] for hit in body["items"]]


# --- The app's search ------------------------------------------------------------------


async def test_searching_needs_a_signed_in_user(assistant_api: AssistantHarness) -> None:
    response = await assistant_api.client.post(SEARCH, json={"query": "Priya"})

    assert response.status_code == 401


async def test_a_user_finds_their_memory_with_the_evidence_it_rests_on(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await signed_in(assistant_api)
    await seed(assistant_api, principal.id)

    body = await search(assistant_api, {"query": "Where does Priya live?"}, headers)

    assert body["query"] == "Where does Priya live?"
    [hit] = body["items"]
    assert (hit["rank"], hit["memory"]["content"], hit["memory"]["status"]) == (
        1,
        SISTER,
        "proposed",
    )
    assert {match["leg"] for match in hit["matched_by"]} == {"lexical", "entity"}
    assert hit["matched_names"] == ["Priya"]
    [source] = hit["sources"]
    assert (source["evidence"], source["content"], source["role"]) == (
        SISTER_MESSAGE,
        SISTER_MESSAGE,
        "supporting",
    )
    assert [(entity["name"], entity["entity_type"]) for entity in hit["entities"]] == [
        ("Priya", "person")
    ]
    legs = {leg["leg"]: leg for leg in body["legs"]}
    assert set(legs) == {"lexical", "entity", "semantic"}
    # No embedding provider is configured: meaning is not used, and that is not a failure.
    assert (legs["semantic"]["used"], legs["semantic"]["error"]) == (False, None)
    assert (body["degraded"], body["reranked"], body["embedding_space"]) == (False, False, None)


async def test_a_user_never_finds_another_user_s_memories(assistant_api: AssistantHarness) -> None:
    owner, owner_headers = await signed_in(assistant_api, "Owner")
    _, stranger_headers = await signed_in(assistant_api, "Stranger")
    await seed(assistant_api, owner.id)

    mine = await search(assistant_api, {"query": "Priya"}, owner_headers)
    theirs = await search(assistant_api, {"query": "Priya"}, stranger_headers)

    assert contents(mine) == [SISTER]
    assert contents(theirs) == []


async def test_filters_reach_the_search(assistant_api: AssistantHarness) -> None:
    principal, headers = await signed_in(assistant_api)
    await seed(assistant_api, principal.id)

    facts = await search(
        assistant_api, {"query": "Priya", "memory_types": ["semantic_fact"]}, headers
    )
    tasks = await search(assistant_api, {"query": "Priya", "memory_types": ["task"]}, headers)
    # The test clock is 2026-10-01 12:00 UTC, when the memory was made.
    later = await search(
        assistant_api, {"query": "Priya", "observed_from": "2026-10-02T00:00:00Z"}, headers
    )

    assert (contents(facts), contents(tasks), contents(later)) == ([SISTER], [], [])


@pytest.mark.parametrize(
    ("body", "error_code"),
    [
        ({"query": ""}, "VALIDATION_ERROR"),
        ({"query": "x" * 501}, "VALIDATION_ERROR"),
        ({"query": "Priya", "limit": 0}, "VALIDATION_ERROR"),
        ({"query": "Priya", "limit": 26}, "VALIDATION_ERROR"),
        ({"query": "Priya", "memory_types": []}, "VALIDATION_ERROR"),
        ({"query": "Priya", "memory_types": ["gossip"]}, "VALIDATION_ERROR"),
        ({"query": "Priya", "observed_from": "2026-10-01T00:00:00"}, "VALIDATION_ERROR"),
        ({"query": "Priya", "owner_id": str(uuid.uuid4())}, "VALIDATION_ERROR"),
        ({"query": "   "}, "INVALID_RETRIEVAL_QUERY"),
        (
            {
                "query": "Priya",
                "observed_from": "2026-10-02T00:00:00Z",
                "observed_to": "2026-10-01T00:00:00Z",
            },
            "INVALID_RETRIEVAL_QUERY",
        ),
    ],
)
async def test_an_invalid_search_is_refused_with_a_reason(
    assistant_api: AssistantHarness, body: dict[str, Any], error_code: str
) -> None:
    _, headers = await signed_in(assistant_api)

    response = await assistant_api.client.post(SEARCH, json=body, headers=headers)

    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == error_code
    assert response.json()["message"]


# --- Meaning, through the real container -----------------------------------------------


async def test_once_indexed_a_memory_is_found_by_meaning(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    embedder = FakeEmbedder(concepts=[("sister", "sibling")])
    async with assistant_api_with(
        embedder=embedder, RETRIEVAL_MIN_SEMANTIC_SIMILARITY=TEST_MIN_SIMILARITY
    ) as harness:
        principal, headers = await signed_in(harness)
        await seed(harness, principal.id)
        before = await search(harness, {"query": "sibling"}, headers)
        indexer = harness.container.memory_indexer
        assert indexer is not None
        report = await indexer.run()
        after = await search(harness, {"query": "sibling"}, headers)

    assert contents(before) == []
    assert report.embedded == 1
    [hit] = after["items"]
    assert hit["memory"]["content"] == SISTER
    assert [match["leg"] for match in hit["matched_by"]] == ["semantic"]
    assert after["embedding_space"] == "fake/bag-of-words/256"
    # The question was embedded as a query, on the user's account.
    question = embedder.calls[-1]
    assert (question.texts, question.input_type) == (("sibling",), EmbeddingInputType.QUERY)
    assert (question.context.origin, question.context.user_id) == (
        LlmCallOrigin.RETRIEVAL,
        principal.id,
    )


async def test_a_failing_embedding_provider_still_answers_by_words_and_names(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    failing = FakeEmbedder(fail_with=IntegrationError("Voyage AI", "could not be reached."))
    async with assistant_api_with(embedder=failing) as harness:
        principal, headers = await signed_in(harness)
        await seed(harness, principal.id)
        body = await search(harness, {"query": "Priya"}, headers)

    assert contents(body) == [SISTER]
    assert body["degraded"] is True
    [semantic] = [leg for leg in body["legs"] if leg["leg"] == "semantic"]
    assert (semantic["used"], semantic["error"]) == (False, "Voyage AI: could not be reached.")


# --- The console's search --------------------------------------------------------------


async def test_the_console_searches_only_the_operator_s_own_store(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await signed_in(assistant_api)
    await seed(assistant_api, principal.id)
    operator_fact = "Priya from work called about the invoice."
    operator_message = "Priya from work called about the invoice"
    await seed(
        assistant_api, None, operator_message, fact(operator_fact, operator_message, "Priya")
    )

    console = await search(assistant_api, {"query": "Priya"})
    mine = await search(assistant_api, {"query": "Priya"}, headers)

    assert contents(console) == [operator_fact]
    assert contents(mine) == [SISTER]


# --- Cooper ----------------------------------------------------------------------------


async def test_cooper_looks_up_the_user_s_memories_and_reads_their_own_words(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await signed_in(assistant_api)
    await seed(assistant_api, principal.id)
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(
        call("search_memories", {"query": "sister"}),
        say("Your sister Priya lives in Pune."),
    )

    events = await stream(assistant_api, headers, thread_id, "Where does my sister live?")

    assert {
        "type": "tool_started",
        "tool": "search_memories",
        "label": "Checking your memories",
    } in events
    assert events[-1]["type"] == "final"
    [first, second] = assistant_api.model.requests
    assert "search_memories" in [tool.name for tool in first.request.tools]
    [results] = [item for item in second.transcript if isinstance(item, ToolResults)]
    [result] = results.results
    assert result.is_error is False
    assert SISTER in result.content
    assert f'Evidence: "{SISTER_MESSAGE}"' in result.content


async def test_cooper_finds_nothing_in_another_user_s_memories(
    assistant_api: AssistantHarness,
) -> None:
    owner, _ = await signed_in(assistant_api, "Owner")
    _, stranger = await signed_in(assistant_api, "Stranger")
    await seed(assistant_api, owner.id)
    thread_id = await main_thread(assistant_api, stranger)
    assistant_api.model.script(
        call("search_memories", {"query": "Priya"}),
        say("I don't have anything saved about Priya."),
    )

    await stream(assistant_api, stranger, thread_id, "What do you know about Priya?")

    [results] = [
        item for item in assistant_api.model.requests[1].transcript if isinstance(item, ToolResults)
    ]
    [result] = results.results
    assert SISTER not in result.content
    assert "rather than guessing" in result.content
