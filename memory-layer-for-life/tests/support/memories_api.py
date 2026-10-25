"""Driving the memory endpoints of the app API in integration tests: users who exist,
messages that become memories through the real pipeline, and JSON shortcuts."""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import EntityType, MemoryType, MessageSource, Sensitivity
from app.domain.principal import Principal
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from app.schemas.extraction import ExtractionOutput
from app.schemas.raw_message import RawMessageCreate
from tests.support.app_api import API
from tests.support.assistant import new_principal
from tests.support.extraction import evidence, extraction, memory, mention

if TYPE_CHECKING:
    from tests.integration.conftest import AssistantHarness

MEMORIES = f"{API}/me/memories"


async def sign_up(
    harness: "AssistantHarness", name: str = "Ada"
) -> tuple[Principal, dict[str, str]]:
    """A signed-in user who exists on the backend."""
    principal = new_principal(name)
    headers = harness.sign_in(principal)
    response = await harness.client.get(f"{API}/me", headers=headers)
    assert response.status_code == 200, response.text
    return principal, headers


def fact(
    content: str,
    message: str,
    *names: str,
    memory_type: MemoryType = MemoryType.SEMANTIC_FACT,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
) -> ExtractionOutput:
    return extraction(
        memory(
            content,
            memory_type=memory_type,
            evidence_refs=[evidence(0, message)],
            mention_indexes=list(range(len(names))),
            sensitivity=sensitivity,
        ),
        mentions=[mention(name, entity_type=EntityType.PERSON) for name in names],
    )


async def told(
    harness: "AssistantHarness",
    principal: Principal,
    message: str,
    output: ExtractionOutput,
    *,
    thread_id: str | None = None,
) -> str:
    """The user's message goes through the pipeline; returns the run's id."""
    harness.extractor.use_script(output)
    [unit] = await harness.container.ingestion_service.ingest(
        [
            [
                RawMessageCreate(
                    source=MessageSource.APP_CHAT,
                    content=message,
                    source_message_id=str(uuid.uuid4()),
                    source_created_at=harness.clock(),
                    metadata={"thread_id": thread_id} if thread_id else {},
                )
            ]
        ],
        owner_id=principal.id,
    )
    await harness.container.pipeline_runner.process_runs([unit.run.id])
    return str(unit.run.id)


async def remembered(
    harness: "AssistantHarness",
    principal: Principal,
    message: str,
    output: ExtractionOutput,
    *,
    thread_id: str | None = None,
) -> str:
    """The id of the one memory a message became."""
    run_id = await told(harness, principal, message, output, thread_id=thread_id)
    async with harness.container.session_factory() as session:
        [memory_id] = await session.scalars(
            select(Memory.id)
            .join(ExtractionResult, ExtractionResult.id == Memory.origin_extraction_result_id)
            .where(ExtractionResult.processing_run_id == uuid.UUID(run_id))
        )
    return str(memory_id)


async def get_json(
    harness: "AssistantHarness", path: str, headers: dict[str, str], status: int = 200
) -> Any:
    response = await harness.client.get(path, headers=headers)
    assert response.status_code == status, response.text
    return response.json()


async def post_json(
    harness: "AssistantHarness",
    path: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    status: int = 200,
) -> Any:
    response = await harness.client.post(path, json=body, headers=headers)
    assert response.status_code == status, response.text
    return response.json() if response.content else None


async def patch_json(
    harness: "AssistantHarness",
    path: str,
    headers: dict[str, str],
    body: dict[str, Any],
    status: int = 200,
) -> Any:
    response = await harness.client.patch(path, json=body, headers=headers)
    assert response.status_code == status, response.text
    return response.json()


def contents(page: dict[str, Any]) -> list[str]:
    return [item["content"] for item in page["items"]]


async def count(
    session_factory: async_sessionmaker[AsyncSession], model: Any, *conditions: Any
) -> int:
    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(model).where(*conditions))
    return int(total or 0)
