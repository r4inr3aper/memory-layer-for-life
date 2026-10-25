"""Memories as their owner manages them in the app, against PostgreSQL: reading with
evidence and history, writing, reviewing, correcting, merging, deleting, people, privacy,
and the data export. The pipeline runs for real around a scripted extractor."""

import uuid

from app.domain.enums import (
    LlmCallOrigin,
    MessageSource,
    ProcessingStatus,
    Sensitivity,
)
from app.domain.errors import TransientExtractionError
from app.domain.retrieval import RetrievalFilters, RetrievalQuery
from app.integrations.llm_calls import LlmCallContext
from app.models.memory_embedding import MemoryEmbedding
from app.models.processing_run import ProcessingRun
from app.models.raw_message import RawMessage
from app.schemas.raw_message import RawMessageCreate
from app.services.processing.runner import PipelineLoop
from tests.integration.conftest import AssistantHarness, AssistantHarnessFactory
from tests.support.app_api import API
from tests.support.embeddings import FakeEmbedder
from tests.support.extraction import abstention
from tests.support.memories_api import (
    MEMORIES,
    contents,
    count,
    fact,
    get_json,
    patch_json,
    post_json,
    remembered,
    sign_up,
    told,
)

# --- Writing and reviewing -------------------------------------------------------------


async def test_a_memory_written_by_hand_is_active_and_has_a_history(
    assistant_api: AssistantHarness,
) -> None:
    _, headers = await sign_up(assistant_api)

    created = await post_json(
        assistant_api,
        MEMORIES,
        headers,
        {"memory_type": "preference", "content": "  I prefer   window seats  "},
        status=201,
    )

    assert created["status"] == "active"
    assert created["created_by"] == "user"
    assert created["content"] == "I prefer window seats"
    assert created["sensitive"] is False
    detail = await get_json(assistant_api, f"{MEMORIES}/{created['id']}", headers)
    assert detail["sources"] == []
    assert [event["action"] for event in detail["history"]] == ["created"]


async def test_the_list_shows_memories_that_may_be_true_unless_asked_for_others(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    kept = await remembered(
        assistant_api, principal, "My sister Priya lives in Pune", fact("Priya lives in Pune.", "x")
    )
    wrong = await remembered(
        assistant_api, principal, "I was born in 1990 I think", fact("Born in 1990.", "x")
    )
    await post_json(assistant_api, f"{MEMORIES}/{wrong}/retract", headers)

    assert contents(await get_json(assistant_api, MEMORIES, headers)) == ["Priya lives in Pune."]
    retracted = await get_json(assistant_api, f"{MEMORIES}?status=retracted", headers)
    assert contents(retracted) == ["Born in 1990."]
    both = await get_json(assistant_api, f"{MEMORIES}?status=retracted&status=proposed", headers)
    assert both["total"] == 2
    proposed = await get_json(assistant_api, f"{MEMORIES}?status=proposed&order=oldest", headers)
    assert [item["id"] for item in proposed["items"]] == [kept]


async def test_accepting_a_proposed_memory_records_it_once(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    memory_id = await remembered(
        assistant_api, principal, "My sister Priya lives in Pune", fact("Priya lives in Pune.", "x")
    )

    first = await post_json(assistant_api, f"{MEMORIES}/{memory_id}/accept", headers)
    again = await post_json(assistant_api, f"{MEMORIES}/{memory_id}/accept", headers)

    assert first["status"] == again["status"] == "active"
    detail = await get_json(assistant_api, f"{MEMORIES}/{memory_id}", headers)
    assert [event["action"] for event in detail["history"]] == ["accepted"]
    assert detail["created_by"] == "pipeline"
    assert detail["sources"][0]["content"] == "My sister Priya lives in Pune"


async def test_accepting_several_memories_skips_what_is_not_proposed(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    first = await remembered(assistant_api, principal, "Priya lives in Pune", fact("A.", "x"))
    second = await remembered(assistant_api, principal, "Raju lives in Goa", fact("B.", "x"))
    retracted = await remembered(assistant_api, principal, "Sam lives in Delhi", fact("C.", "x"))
    await post_json(assistant_api, f"{MEMORIES}/{retracted}/retract", headers)
    _, stranger = await sign_up(assistant_api, "Eve")

    result = await post_json(
        assistant_api,
        f"{MEMORIES}/review/accept",
        headers,
        {"memory_ids": [first, second, retracted, str(uuid.uuid4())]},
    )
    theirs = await post_json(
        assistant_api, f"{MEMORIES}/review/accept", stranger, {"memory_ids": [first]}
    )

    assert result == {"accepted": 2}
    assert theirs == {"accepted": 0}
    active = await get_json(assistant_api, f"{MEMORIES}?status=active", headers)
    assert sorted(item["id"] for item in active["items"]) == sorted([first, second])


async def test_a_retracted_memory_is_kept_out_until_restored(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    memory_id = await remembered(
        assistant_api, principal, "Raju owes me 500 rupees", fact("Raju owes the user 500.", "x")
    )

    retracted = await post_json(assistant_api, f"{MEMORIES}/{memory_id}/retract", headers)
    refused = await assistant_api.client.post(f"{MEMORIES}/{memory_id}/accept", headers=headers)
    search = await post_json(assistant_api, f"{MEMORIES}/search", headers, {"query": "Raju"})
    restored = await post_json(assistant_api, f"{MEMORIES}/{memory_id}/restore", headers)

    assert retracted["status"] == "retracted"
    assert refused.status_code == 409
    assert refused.json()["error_code"] == "MEMORY_STATE_CONFLICT"
    assert search["items"] == []
    assert restored["status"] == "active"
    detail = await get_json(assistant_api, f"{MEMORIES}/{memory_id}", headers)
    assert [event["action"] for event in detail["history"]] == ["retracted", "restored"]


# --- Correcting and editing ------------------------------------------------------------


async def test_correcting_the_text_makes_a_new_version_that_keeps_the_evidence(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    old = await remembered(
        assistant_api,
        principal,
        "My sister Priya lives in Pune",
        fact("Priya lives in Pune.", "My sister Priya lives in Pune", "Priya"),
    )

    corrected = await patch_json(
        assistant_api, f"{MEMORIES}/{old}", headers, {"content": "Priya lives in Mumbai now."}
    )

    new = corrected["id"]
    assert new != old
    assert (corrected["status"], corrected["created_by"]) == ("active", "user")
    assert corrected["supersedes_memory_id"] == old
    detail = await get_json(assistant_api, f"{MEMORIES}/{new}", headers)
    assert [source["content"] for source in detail["sources"]] == ["My sister Priya lives in Pune"]
    assert [entity["canonical_name"] for entity in detail["entities"]] == ["Priya"]
    [event] = detail["history"]
    assert event["action"] == "corrected"
    assert event["details"]["previous_content"] == "Priya lives in Pune."
    assert [version["id"] for version in detail["replaced"]] == [old]

    previous = await get_json(assistant_api, f"{MEMORIES}/{old}", headers)
    assert previous["status"] == "superseded"
    assert previous["replaced_by_id"] == new
    stale = await assistant_api.client.patch(
        f"{MEMORIES}/{old}", json={"content": "Elsewhere"}, headers=headers
    )
    assert stale.status_code == 409
    assert contents(await get_json(assistant_api, MEMORIES, headers)) == [
        "Priya lives in Mumbai now."
    ]


async def test_kind_and_sensitivity_change_in_place(assistant_api: AssistantHarness) -> None:
    principal, headers = await sign_up(assistant_api)
    memory_id = await remembered(
        assistant_api, principal, "I feel drained lately", fact("Feels drained.", "x")
    )

    changed = await patch_json(
        assistant_api,
        f"{MEMORIES}/{memory_id}",
        headers,
        {"memory_type": "reflection", "sensitive": True},
    )
    unchanged = await assistant_api.client.patch(
        f"{MEMORIES}/{memory_id}", json={"sensitive": True}, headers=headers
    )

    assert changed["id"] == memory_id
    assert (changed["memory_type"], changed["sensitive"]) == ("reflection", True)
    assert unchanged.status_code == 422
    detail = await get_json(assistant_api, f"{MEMORIES}/{memory_id}", headers)
    [event] = detail["history"]
    assert event["details"]["changes"] == {
        "memory_type": {"from": "semantic_fact", "to": "reflection"},
        "sensitive": {"from": False, "to": True},
    }


async def test_an_empty_edit_is_refused(assistant_api: AssistantHarness) -> None:
    _, headers = await sign_up(assistant_api)
    created = await post_json(assistant_api, MEMORIES, headers, {"content": "A note"}, status=201)

    for body in ({}, {"content": "   "}, {"content": "x" * 2001}):
        response = await assistant_api.client.patch(
            f"{MEMORIES}/{created['id']}", json=body, headers=headers
        )
        assert response.status_code == 422, body


# --- Privacy ---------------------------------------------------------------------------


async def test_a_sensitive_memory_is_shown_to_its_owner_but_never_given_to_a_model(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    embedder = FakeEmbedder()
    async with assistant_api_with(embedder=embedder) as harness:
        principal, headers = await sign_up(harness)
        private = await remembered(
            harness,
            principal,
            "Therapy with Dr Rao on Friday",
            fact("Has therapy with Dr Rao.", "x", sensitivity=Sensitivity.SENSITIVE),
        )
        plain = await remembered(
            harness, principal, "Lunch with Dr Rao on Monday", fact("Lunch with Dr Rao.", "x")
        )
        indexer = harness.container.memory_indexer
        assert indexer is not None
        await indexer.run()

        own = await post_json(harness, f"{MEMORIES}/search", headers, {"query": "Dr Rao"})
        for_a_model = await harness.container.retrieval_engine.search(
            RetrievalQuery(text="Dr Rao", owner_id=principal.id, filters=RetrievalFilters()),
            context=LlmCallContext(origin=LlmCallOrigin.ASSISTANT, user_id=principal.id),
        )

        assert {item["memory"]["id"]: item["memory"]["sensitive"] for item in own["items"]} == {
            private: True,
            plain: False,
        }
        assert [str(item.memory.id) for item in for_a_model.items] == [plain]
        assert not any("therapy" in text.lower() for text in embedder.texts_embedded)
        sessions = harness.container.session_factory
        assert await count(sessions, MemoryEmbedding, MemoryEmbedding.memory_id == private) == 0

        # Marking a memory sensitive removes its embedding at once.
        assert await count(sessions, MemoryEmbedding, MemoryEmbedding.memory_id == plain) == 1
        await patch_json(harness, f"{MEMORIES}/{plain}", headers, {"sensitive": True})
        assert await count(sessions, MemoryEmbedding, MemoryEmbedding.memory_id == plain) == 0
        await indexer.run()
        assert await count(sessions, MemoryEmbedding) == 0


# --- Deleting --------------------------------------------------------------------------


async def test_deleting_a_memory_deletes_its_older_versions_and_keeps_the_message(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    first = await remembered(
        assistant_api, principal, "Raju owes me 500 rupees", fact("Raju owes 500.", "x")
    )
    second = (await patch_json(assistant_api, f"{MEMORIES}/{first}", headers, {"content": "600"}))[
        "id"
    ]
    third = (await patch_json(assistant_api, f"{MEMORIES}/{second}", headers, {"content": "700"}))[
        "id"
    ]
    other = await remembered(assistant_api, principal, "Priya lives in Pune", fact("Pune.", "x"))

    response = await assistant_api.client.delete(f"{MEMORIES}/{third}", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": 3}
    for memory_id in (first, second, third):
        await get_json(assistant_api, f"{MEMORIES}/{memory_id}", headers, status=404)
    assert contents(await get_json(assistant_api, MEMORIES, headers)) == ["Pune."]
    await get_json(assistant_api, f"{MEMORIES}/{other}", headers)
    sessions = assistant_api.container.session_factory
    assert await count(sessions, RawMessage, RawMessage.content == "Raju owes me 500 rupees") == 1


async def test_another_user_s_memory_reads_as_missing(assistant_api: AssistantHarness) -> None:
    principal, _ = await sign_up(assistant_api)
    memory_id = await remembered(
        assistant_api, principal, "My sister Priya lives in Pune", fact("Priya.", "x")
    )
    _, stranger = await sign_up(assistant_api, "Eve")

    assert (
        await assistant_api.client.get(f"{MEMORIES}/{memory_id}", headers=stranger)
    ).status_code == 404
    edit = await assistant_api.client.patch(
        f"{MEMORIES}/{memory_id}", json={"content": "Mine now"}, headers=stranger
    )
    assert edit.status_code == 404
    assert (
        await assistant_api.client.delete(f"{MEMORIES}/{memory_id}", headers=stranger)
    ).status_code == 404
    accept = await assistant_api.client.post(f"{MEMORIES}/{memory_id}/accept", headers=stranger)
    assert accept.status_code == 404


# --- Suggestions -----------------------------------------------------------------------


async def test_one_fact_told_twice_is_suggested_as_a_duplicate_and_merges_into_one(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    older = await remembered(
        assistant_api,
        principal,
        "My sister Priya lives in Pune",
        fact("Priya lives in Pune.", "My sister Priya lives in Pune", "Priya"),
    )
    newer = await remembered(
        assistant_api,
        principal,
        "Priya, my sister, lives in Pune",
        fact("Priya lives in Pune.", "Priya, my sister, lives in Pune", "Priya"),
    )

    inbox = await get_json(assistant_api, f"{MEMORIES}/review", headers)

    assert inbox["proposed_count"] == 2
    [suggestion] = inbox["suggestions"]
    assert suggestion["kind"] == "duplicate"
    assert (suggestion["first"]["id"], suggestion["second"]["id"]) == (older, newer)
    assert suggestion["similarity"] == 1.0
    assert suggestion["shared_entities"] == 1

    kept = await post_json(
        assistant_api, f"{MEMORIES}/{newer}/merge", headers, {"other_memory_id": older}
    )

    assert kept["status"] == "active"
    detail = await get_json(assistant_api, f"{MEMORIES}/{newer}", headers)
    assert sorted(source["content"] for source in detail["sources"]) == [
        "My sister Priya lives in Pune",
        "Priya, my sister, lives in Pune",
    ]
    assert [entity["canonical_name"] for entity in detail["entities"]] == ["Priya"]
    assert [event["action"] for event in detail["history"]] == ["merged"]
    assert [version["id"] for version in detail["replaced"]] == [older]
    retired = await get_json(assistant_api, f"{MEMORIES}/{older}", headers)
    assert (retired["status"], retired["replaced_by_id"]) == ("superseded", newer)
    after = await get_json(assistant_api, f"{MEMORIES}/review", headers)
    assert after["suggestions"] == []
    assert after["proposed_count"] == 0


async def test_different_amounts_owed_by_one_person_are_suggested_as_a_conflict(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    old = await remembered(
        assistant_api,
        principal,
        "Raju owes me 500 rupees",
        fact("Raju owes the user 500 rupees.", "Raju owes me 500 rupees", "Raju"),
    )
    new = await remembered(
        assistant_api,
        principal,
        "Raju owes me 700 rupees now",
        fact("Raju owes the user 700 rupees.", "Raju owes me 700 rupees now", "Raju"),
    )

    [suggestion] = (await get_json(assistant_api, f"{MEMORIES}/review", headers))["suggestions"]
    assert suggestion["kind"] == "conflict"

    kept = await post_json(
        assistant_api, f"{MEMORIES}/{new}/replace", headers, {"other_memory_id": old}
    )

    assert kept["status"] == "active"
    outdated = await get_json(assistant_api, f"{MEMORIES}/{old}", headers)
    assert outdated["status"] == "superseded"
    # Replacing keeps the evidence apart: the old message still backs only the old memory.
    current = await get_json(assistant_api, f"{MEMORIES}/{new}", headers)
    assert [source["content"] for source in current["sources"]] == ["Raju owes me 700 rupees now"]
    assert (await get_json(assistant_api, f"{MEMORIES}/review", headers))["suggestions"] == []


async def test_a_dismissed_suggestion_is_not_shown_again(assistant_api: AssistantHarness) -> None:
    principal, headers = await sign_up(assistant_api)
    first = await remembered(
        assistant_api, principal, "Raju owes me 500", fact("Raju owes 500.", "x", "Raju")
    )
    second = await remembered(
        assistant_api, principal, "Raju owes me 700", fact("Raju owes 700.", "x", "Raju")
    )

    await post_json(
        assistant_api,
        f"{MEMORIES}/review/dismiss",
        headers,
        {"first_memory_id": second, "second_memory_id": first, "kind": "conflict"},
        status=204,
    )

    assert (await get_json(assistant_api, f"{MEMORIES}/review", headers))["suggestions"] == []
    detail = await get_json(assistant_api, f"{MEMORIES}/{first}", headers)
    [event] = detail["history"]
    assert event["action"] == "suggestion_dismissed"
    assert event["details"] == {"other_memory_id": second, "kind": "conflict"}


async def test_the_same_fact_in_other_words_is_found_by_meaning(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    async with assistant_api_with(embedder=FakeEmbedder()) as harness:
        principal, headers = await sign_up(harness)
        await remembered(
            harness, principal, "Priya lives in Pune", fact("Priya lives in Pune.", "x")
        )
        await remembered(
            harness, principal, "Pune is where Priya lives", fact("Pune is where Priya lives.", "x")
        )
        without_embeddings = await get_json(harness, f"{MEMORIES}/review", headers)
        indexer = harness.container.memory_indexer
        assert indexer is not None
        await indexer.run()

        with_embeddings = await get_json(harness, f"{MEMORIES}/review", headers)

    assert without_embeddings["suggestions"] == []
    [suggestion] = with_embeddings["suggestions"]
    assert suggestion["kind"] == "duplicate"
    assert suggestion["similarity"] > 0.93


# --- Held back -------------------------------------------------------------------------


async def test_a_held_back_message_can_be_saved_as_a_memory(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    thread = await post_json(assistant_api, f"{API}/threads", headers, {}, status=201)
    run_id = await told(
        assistant_api,
        principal,
        "the thing with K, same as before",
        abstention(),
        thread_id=thread["id"],
    )

    inbox = await get_json(assistant_api, f"{MEMORIES}/review", headers)

    assert inbox["held_back_count"] == 1
    [held] = inbox["held_back"]
    assert (held["run_id"], held["reason"]) == (run_id, "unclear")
    [message] = held["messages"]
    assert message["content"] == "the thing with K, same as before"
    assert message["thread_id"] == thread["id"]

    saved = await post_json(
        assistant_api,
        f"{MEMORIES}/held-back/{run_id}/save",
        headers,
        {"memory_type": "note", "content": "K's project is on hold, as before."},
        status=201,
    )

    assert (saved["status"], saved["created_by"]) == ("active", "user")
    detail = await get_json(assistant_api, f"{MEMORIES}/{saved['id']}", headers)
    [source] = detail["sources"]
    assert source["content"] == "the thing with K, same as before"
    assert source["thread_id"] == thread["id"]
    after = await get_json(assistant_api, f"{MEMORIES}/review", headers)
    assert (after["held_back"], after["held_back_count"]) == ([], 0)
    again = await assistant_api.client.post(
        f"{MEMORIES}/held-back/{run_id}/save", json={"content": "Twice"}, headers=headers
    )
    assert again.status_code == 404
    async with assistant_api.container.session_factory() as session:
        run = await session.get(ProcessingRun, uuid.UUID(run_id))
    assert run is not None and run.status == ProcessingStatus.NEEDS_REVIEW.value


async def test_a_held_back_message_can_be_dismissed_by_its_owner_only(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    run_id = await told(assistant_api, principal, "hmm ok so anyway that", abstention())
    _, stranger = await sign_up(assistant_api, "Eve")

    theirs = await assistant_api.client.post(
        f"{MEMORIES}/held-back/{run_id}/dismiss", headers=stranger
    )
    await post_json(assistant_api, f"{MEMORIES}/held-back/{run_id}/dismiss", headers, status=204)

    assert theirs.status_code == 404
    assert (await get_json(assistant_api, f"{MEMORIES}/review", headers))["held_back"] == []


# --- People ----------------------------------------------------------------------------


async def test_people_are_listed_by_how_many_memories_mention_them(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    await remembered(assistant_api, principal, "Priya lives in Pune", fact("A.", "x", "Priya"))
    await remembered(assistant_api, principal, "Priya likes tea", fact("B.", "x", "Priya"))
    gone = await remembered(assistant_api, principal, "Raju plays chess", fact("C.", "x", "Raju"))
    await post_json(assistant_api, f"{MEMORIES}/{gone}/retract", headers)

    people = await get_json(assistant_api, f"{API}/me/people", headers)

    assert [(person["name"], person["memory_count"]) for person in people["items"]] == [
        ("Priya", 2)
    ]
    priya = people["items"][0]
    detail = await get_json(assistant_api, f"{API}/me/people/{priya['id']}", headers)
    assert sorted(memory["content"] for memory in detail["memories"]) == ["A.", "B."]
    places = await get_json(assistant_api, f"{API}/me/people?entity_type=place", headers)
    assert places["items"] == []


async def test_renaming_a_person_keeps_the_old_name_for_later_messages(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    await remembered(assistant_api, principal, "Priya lives in Pune", fact("A.", "x", "Priya"))
    [priya] = (await get_json(assistant_api, f"{API}/me/people", headers))["items"]

    renamed = await patch_json(
        assistant_api, f"{API}/me/people/{priya['id']}", headers, {"name": "Priya Sharma"}
    )
    await remembered(assistant_api, principal, "Priya likes tea", fact("B.", "x", "Priya"))

    assert (renamed["name"], renamed["aliases"]) == ("Priya Sharma", ["Priya"])
    [person] = (await get_json(assistant_api, f"{API}/me/people", headers))["items"]
    assert (person["id"], person["name"], person["memory_count"]) == (
        priya["id"],
        "Priya Sharma",
        2,
    )


async def test_merging_two_people_moves_their_memories(assistant_api: AssistantHarness) -> None:
    principal, headers = await sign_up(assistant_api)
    await remembered(assistant_api, principal, "Priya lives in Pune", fact("A.", "x", "Priya"))
    await remembered(assistant_api, principal, "Pri likes tea", fact("B.", "x", "Pri"))
    people = {
        person["name"]: person["id"]
        for person in (await get_json(assistant_api, f"{API}/me/people", headers))["items"]
    }

    merged = await post_json(
        assistant_api,
        f"{API}/me/people/{people['Priya']}/merge",
        headers,
        {"other_person_id": people["Pri"]},
    )

    assert (merged["name"], merged["memory_count"], merged["aliases"]) == ("Priya", 2, ["Pri"])
    [person] = (await get_json(assistant_api, f"{API}/me/people", headers))["items"]
    assert person["id"] == people["Priya"]
    # The merged person's link answers with the one they were merged into.
    found = await get_json(assistant_api, f"{API}/me/people/{people['Pri']}", headers)
    assert found["id"] == people["Priya"]
    # A later "Pri" resolves to Priya.
    await remembered(assistant_api, principal, "Pri called today", fact("C.", "x", "Pri"))
    [person] = (await get_json(assistant_api, f"{API}/me/people", headers))["items"]
    assert person["memory_count"] == 3


# --- Chats, search, export, retries ----------------------------------------------------


async def test_deleting_a_chat_keeps_its_memories(assistant_api: AssistantHarness) -> None:
    principal, headers = await sign_up(assistant_api)
    thread = await post_json(assistant_api, f"{API}/threads", headers, {}, status=201)
    memory_id = await remembered(
        assistant_api,
        principal,
        "My sister Priya lives in Pune",
        fact("Priya lives in Pune.", "x"),
        thread_id=thread["id"],
    )
    before = await get_json(assistant_api, f"{MEMORIES}/{memory_id}", headers)

    response = await assistant_api.client.delete(f"{API}/threads/{thread['id']}", headers=headers)

    assert response.status_code == 204
    after = await get_json(assistant_api, f"{MEMORIES}/{memory_id}", headers)
    assert before["sources"][0]["thread_id"] == thread["id"]
    assert after["sources"][0]["thread_id"] is None
    assert after["sources"][0]["content"] == "My sister Priya lives in Pune"


async def test_search_returns_the_same_text_once(assistant_api: AssistantHarness) -> None:
    principal, headers = await sign_up(assistant_api)
    await remembered(
        assistant_api, principal, "Priya lives in Pune", fact("Priya lives in Pune.", "x")
    )
    await remembered(
        assistant_api, principal, "Priya is in Pune", fact("Priya lives in Pune.", "x")
    )
    await remembered(assistant_api, principal, "Priya likes Pune", fact("Priya likes Pune.", "x"))

    result = await post_json(assistant_api, f"{MEMORIES}/search", headers, {"query": "Priya Pune"})

    assert sorted(item["memory"]["content"] for item in result["items"]) == [
        "Priya likes Pune.",
        "Priya lives in Pune.",
    ]


async def test_the_export_holds_everything_and_downloads_as_a_file(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    thread = await post_json(
        assistant_api, f"{API}/threads", headers, {"title": "Trip"}, status=201
    )
    memory_id = await remembered(
        assistant_api,
        principal,
        "Therapy on Friday",
        fact("Has therapy on Friday.", "x", sensitivity=Sensitivity.SENSITIVE),
    )
    await post_json(assistant_api, f"{MEMORIES}/{memory_id}/accept", headers)
    _, stranger = await sign_up(assistant_api, "Eve")
    await post_json(assistant_api, MEMORIES, stranger, {"content": "Eve's secret"}, status=201)

    response = await assistant_api.client.get(f"{API}/me/export", headers=headers)

    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"].startswith('attachment; filename="muse-export-')
    document = response.json()
    assert (document["format"], document["version"]) == ("muse-export", 1)
    assert document["account"]["id"] == str(principal.id)
    [exported] = document["memories"]
    assert (exported["content"], exported["sensitive"], exported["status"]) == (
        "Has therapy on Friday.",
        True,
        "active",
    )
    assert exported["evidence"][0]["message"] == "Therapy on Friday"
    assert [entry["action"] for entry in exported["history"]] == ["accepted"]
    assert [chat["title"] for chat in document["chats"]] == ["Trip"]
    assert thread["id"] in {chat["id"] for chat in document["chats"]}
    assert "Eve's secret" not in response.text


async def test_a_failed_save_is_retried_by_the_pipeline_loop(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    harness = assistant_api
    harness.extractor.use_script(
        TransientExtractionError("The provider is busy."),
        fact("Priya lives in Pune.", "My sister Priya lives in Pune"),
    )
    [unit] = await harness.container.ingestion_service.ingest(
        [
            [
                RawMessageCreate(
                    source=MessageSource.APP_CHAT, content="My sister Priya lives in Pune"
                )
            ]
        ],
        owner_id=principal.id,
    )
    [first] = await harness.container.pipeline_runner.process_runs([unit.run.id])
    loop = PipelineLoop(harness.container.pipeline_runner, interval_seconds=60, batch_size=5)

    too_soon = await loop.run_once()
    harness.clock.advance(minutes=5)
    retried = await loop.run_once()

    assert first.status is ProcessingStatus.QUEUED
    assert too_soon == []
    assert [outcome.status for outcome in retried] == [ProcessingStatus.SUCCEEDED]
    assert contents(await get_json(harness, MEMORIES, headers)) == ["Priya lives in Pune."]
