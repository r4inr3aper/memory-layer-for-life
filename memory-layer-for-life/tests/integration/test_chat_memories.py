"""Chats become memories: capture, ownership, privacy, and deletion, against PostgreSQL.

The memory pipeline runs for real around a scripted extractor, so these cover everything
but the model: evidence, entity resolution, memories, and their owner.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import EntityType, MemoryType, MessageSource
from app.models.entity import Entity
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from app.models.processing_run import ProcessingRun
from app.models.raw_message import RawMessage
from app.schemas.raw_message import RawMessageCreate
from app.services.memory_capture import worth_capturing
from tests.integration.conftest import AssistantHarness, AssistantHarnessFactory
from tests.support.app_api import API, main_thread, stream
from tests.support.assistant import new_principal, say
from tests.support.extraction import evidence, extraction, memory, mention

SISTER = "My sister Priya lives in Pune"


def sister_fact(text: str = SISTER) -> Any:
    return extraction(
        memory(
            "The user's sister Priya lives in Pune.",
            memory_type=MemoryType.SEMANTIC_FACT,
            evidence_refs=[evidence(0, text)],
            mention_indexes=[0],
        ),
        mentions=[mention("Priya", entity_type=EntityType.PERSON)],
    )


async def say_to_cooper(
    harness: AssistantHarness, headers: dict[str, str], text: str, *, timezone: str = "UTC"
) -> None:
    harness.model.script(say("Noted."))
    events = await stream(
        harness, headers, await main_thread(harness, headers), text, timezone=timezone
    )
    assert events[-1]["type"] == "final"
    await harness.container.background.wait()


async def my_memories(harness: AssistantHarness, headers: dict[str, str]) -> dict[str, Any]:
    response = await harness.client.get(f"{API}/me/memories", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def count(
    session_factory: async_sessionmaker[AsyncSession], model: Any, *conditions: Any
) -> int:
    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(model).where(*conditions))
    return int(total or 0)


# --- Capture ---------------------------------------------------------------------------


async def test_a_chat_message_becomes_the_user_s_own_memory(
    assistant_api_with: AssistantHarnessFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with assistant_api_with(MEMORY_CAPTURE_ENABLED=True) as harness:
        principal = new_principal()
        headers = harness.sign_in(principal)
        harness.extractor.use_script(sister_fact())

        await say_to_cooper(harness, headers, SISTER)
        body = await my_memories(harness, headers)

    assert body["total"] == 1
    [item] = body["items"]
    assert (item["content"], item["memory_type"], item["status"]) == (
        "The user's sister Priya lives in Pune.",
        "semantic_fact",
        "proposed",
    )
    # Only the user's words were sent to the extractor, never Cooper's reply.
    [request] = harness.extractor.requests
    assert [message.text for message in request.messages] == [SISTER]
    # The extraction call counts in the user's cost.
    assert request.call_context is not None
    assert request.call_context.user_id == principal.id
    async with session_factory() as session:
        evidence_row = await session.scalar(select(RawMessage))
        entity = await session.scalar(select(Entity))
        stored = await session.scalar(select(Memory))
    assert evidence_row is not None and entity is not None and stored is not None
    assert (evidence_row.source, evidence_row.owner_id) == (
        MessageSource.APP_CHAT.value,
        principal.id,
    )
    assert (entity.canonical_name, entity.owner_id) == ("Priya", principal.id)
    assert stored.owner_id == principal.id


async def test_dates_in_a_message_are_read_in_the_user_s_timezone(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    async with assistant_api_with(MEMORY_CAPTURE_ENABLED=True) as harness:
        headers = harness.sign_in(new_principal())
        harness.extractor.use_script(sister_fact())

        await say_to_cooper(harness, headers, SISTER, timezone="Asia/Kolkata")

    [request] = harness.extractor.requests
    assert request.timezone_name == "Asia/Kolkata"


async def test_the_same_message_is_captured_once(
    assistant_api_with: AssistantHarnessFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with assistant_api_with(MEMORY_CAPTURE_ENABLED=True) as harness:
        principal = new_principal()
        headers = harness.sign_in(principal)
        harness.extractor.use_script(sister_fact())
        await say_to_cooper(harness, headers, SISTER)
        [message] = (
            await harness.client.get(
                f"{API}/threads/{await main_thread(harness, headers)}/messages", headers=headers
            )
        ).json()["items"][:1]

        # Capturing it again (as a retry would) reuses the stored evidence and run.
        [unit] = await harness.container.ingestion_service.ingest(
            [
                [
                    RawMessageCreate(
                        source=MessageSource.APP_CHAT,
                        content=SISTER,
                        source_message_id=message["id"],
                    )
                ]
            ],
            owner_id=principal.id,
        )

    assert (unit.run.created, unit.messages[0].created) == (False, False)
    assert await count(session_factory, RawMessage) == 1


async def test_short_messages_and_files_alone_are_not_captured(
    assistant_api_with: AssistantHarnessFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with assistant_api_with(MEMORY_CAPTURE_ENABLED=True) as harness:
        headers = harness.sign_in(new_principal())
        await say_to_cooper(harness, headers, "hi there")

    assert harness.extractor.call_count == 0
    assert await count(session_factory, RawMessage) == 0


async def test_a_user_can_turn_capture_off(
    assistant_api_with: AssistantHarnessFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with assistant_api_with(MEMORY_CAPTURE_ENABLED=True) as harness:
        headers = harness.sign_in(new_principal())
        switched = await harness.client.patch(
            f"{API}/me", json={"memory_capture_enabled": False}, headers=headers
        )
        await say_to_cooper(harness, headers, SISTER)

    assert switched.json()["memory_capture_enabled"] is False
    assert await count(session_factory, RawMessage) == 0


async def test_the_operator_can_turn_capture_off_for_everyone(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = assistant_api.sign_in(new_principal())
    me = (await assistant_api.client.get(f"{API}/me", headers=headers)).json()

    await say_to_cooper(assistant_api, headers, SISTER)

    assert me["memory_capture_enabled"] is True
    assert await count(session_factory, RawMessage) == 0


async def test_a_failed_extraction_never_reaches_the_chat(
    assistant_api_with: AssistantHarnessFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with assistant_api_with(MEMORY_CAPTURE_ENABLED=True) as harness:
        headers = harness.sign_in(new_principal())
        harness.extractor.use_script(RuntimeError("model down"))

        await say_to_cooper(harness, headers, SISTER)  # asserts the reply was final
        memories = await my_memories(harness, headers)

    # The evidence is kept for the pipeline's own retry; no memory was made.
    assert await count(session_factory, RawMessage) == 1
    assert memories["total"] == 0


# --- Ownership -------------------------------------------------------------------------


async def test_namesakes_of_different_users_stay_separate_people(
    assistant_api_with: AssistantHarnessFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with assistant_api_with(MEMORY_CAPTURE_ENABLED=True) as harness:
        first = new_principal("First")
        second = new_principal("Second")
        harness.extractor.use_script(sister_fact())
        await say_to_cooper(harness, harness.sign_in(first), SISTER)
        await say_to_cooper(harness, harness.sign_in(second), SISTER)
        harness.extractor.use_script(sister_fact("Priya called me today about Pune"))
        await say_to_cooper(harness, harness.sign_in(first), "Priya called me today about Pune")

    async with session_factory() as session:
        entities = list(await session.scalars(select(Entity).order_by(Entity.created_at)))
    # One Priya per user; the first user's second mention resolved to their own Priya.
    assert sorted(str(entity.owner_id) for entity in entities) == sorted(
        [str(first.id), str(second.id)]
    )


async def test_each_user_sees_only_their_own_memories(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    async with assistant_api_with(MEMORY_CAPTURE_ENABLED=True) as harness:
        owner = harness.sign_in(new_principal("Owner"))
        stranger = harness.sign_in(new_principal("Stranger"))
        harness.extractor.use_script(sister_fact())
        await say_to_cooper(harness, owner, SISTER)

        mine = await my_memories(harness, owner)
        theirs = await my_memories(harness, stranger)

    assert (mine["total"], theirs["total"]) == (1, 0)


async def test_the_unauthenticated_console_never_shows_users_data(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    async with assistant_api_with(MEMORY_CAPTURE_ENABLED=True) as harness:
        headers = harness.sign_in(new_principal())
        harness.extractor.use_script(sister_fact())
        await say_to_cooper(harness, headers, SISTER)
        [item] = (await my_memories(harness, headers))["items"]
        async with harness.container.session_factory() as session:
            run_id = await session.scalar(select(ProcessingRun.id))

        console_memories = await harness.client.get(f"{API}/memories")
        console_memory = await harness.client.get(f"{API}/memories/{item['id']}")
        console_runs = await harness.client.get(f"{API}/processing/runs")
        console_run = await harness.client.get(f"{API}/processing/runs/{run_id}")

    assert console_memories.json()["total"] == 0
    assert console_memory.status_code == 404
    assert console_runs.json()["total"] == 0
    assert console_run.status_code == 404


# --- Deletion --------------------------------------------------------------------------


async def test_deleting_the_account_deletes_its_memories_and_nothing_else(
    assistant_api_with: AssistantHarnessFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with assistant_api_with(MEMORY_CAPTURE_ENABLED=True) as harness:
        principal = new_principal()
        headers = harness.sign_in(principal)
        harness.extractor.use_script(sister_fact())
        await say_to_cooper(harness, headers, SISTER)
        # The operator's own store holds a namesake that must survive.
        [operator_unit] = await harness.container.ingestion_service.ingest(
            [[RawMessageCreate(source=MessageSource.MANUAL_CAPTURE, content=SISTER)]]
        )
        await harness.container.pipeline_runner.process_runs([operator_unit.run.id])

        deleted = await harness.client.delete(f"{API}/me", headers=headers)

    assert deleted.status_code == 200, deleted.text
    for model in (RawMessage, Entity, Memory):
        assert await count(session_factory, model, model.owner_id == principal.id) == 0
        assert await count(session_factory, model, model.owner_id.is_(None)) == 1
    assert await count(session_factory, ProcessingRun) == 1
    assert await count(session_factory, ExtractionResult) == 1


def test_only_messages_of_a_few_words_are_worth_capturing() -> None:
    assert not worth_capturing("hi")
    assert not worth_capturing("thanks a")
    assert worth_capturing("I like tea")
    assert not worth_capturing("   ")
