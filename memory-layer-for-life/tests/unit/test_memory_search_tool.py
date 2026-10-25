"""Cooper's search_memories tool: input checks, the search it asks for, and what the
model reads back."""

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.domain.enums import (
    EntityType,
    LlmCallOrigin,
    MemoryOrigin,
    MemoryStatus,
    MemoryType,
    MessageSource,
    RetrievalLeg,
    SourceRole,
)
from app.domain.retrieval import LegHit, RetrievalQuery
from app.integrations.llm_calls import LlmCallContext
from app.services.assistant.context import TurnContext
from app.services.assistant.tools import AssistantToolbox, SearchMemoriesTool, format_memories
from app.services.queries import MemoryView
from app.services.retrieval.engine import (
    LegReport,
    RetrievalResult,
    RetrievedEntity,
    RetrievedMemory,
    RetrievedSource,
)
from tests.support.assistant import new_principal

NOTED = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)


def retrieved(content: str, *, status: MemoryStatus = MemoryStatus.PROPOSED) -> RetrievedMemory:
    memory_id = uuid.uuid4()
    return RetrievedMemory(
        memory=MemoryView(
            id=memory_id,
            memory_type=MemoryType.SEMANTIC_FACT,
            content=content,
            normalized_content=None,
            status=status,
            confidence=0.9,
            valid_from=None,
            valid_until=None,
            observed_at=None,
            supersedes_memory_id=None,
            metadata={},
            created_at=NOTED,
            updated_at=NOTED,
            created_by=MemoryOrigin.PIPELINE,
            sensitive=False,
        ),
        rank=1,
        score=0.03,
        legs={RetrievalLeg.LEXICAL: LegHit(memory_id=memory_id, rank=1, score=0.5)},
        rerank_score=None,
        matched_names=(),
        sources=(
            RetrievedSource(
                raw_message_id=uuid.uuid4(),
                role=SourceRole.SUPPORTING,
                source=MessageSource.APP_CHAT,
                sent_at=NOTED,
                evidence="My sister Priya lives in Pune",
                content="My sister Priya lives in Pune, near the river",
            ),
        ),
        entities=(
            RetrievedEntity(entity_id=uuid.uuid4(), entity_type=EntityType.PERSON, name="Priya"),
        ),
    )


def result(*items: RetrievedMemory, degraded: bool = False) -> RetrievalResult:
    legs = (
        LegReport(
            leg=RetrievalLeg.SEMANTIC,
            used=not degraded,
            candidates=0,
            duration_ms=1,
            error="Voyage AI: could not be reached." if degraded else None,
        ),
    )
    return RetrievalResult(
        query="sister",
        items=items,
        legs=legs,
        embedding_space=None,
        reranked=False,
        duration_ms=3,
    )


class FakeEngine:
    def __init__(self, answer: RetrievalResult) -> None:
        self.answer = answer
        self.queries: list[tuple[RetrievalQuery, LlmCallContext]] = []

    async def search(self, query: RetrievalQuery, *, context: LlmCallContext) -> RetrievalResult:
        self.queries.append((query, context))
        return self.answer


def turn(timezone_name: str = "Asia/Kolkata") -> TurnContext:
    async def emit(event: object) -> None:
        return None

    return TurnContext(
        principal=new_principal(), timezone_name=timezone_name, original_prompt="hi", emit=emit
    )


# --- What the model reads ----------------------------------------------------------------


def test_memories_read_with_their_kind_date_review_and_the_user_s_own_words() -> None:
    text = format_memories(
        result(retrieved("The user's sister Priya lives in Pune.")), timezone_name="Asia/Kolkata"
    )

    assert text.splitlines() == [
        "Memories from the user's own earlier messages, most relevant first:",
        "1. [Fact, noted 02 Oct 2026, not yet reviewed] The user's sister Priya lives in Pune.",
        '   The user wrote: "My sister Priya lives in Pune"',
    ]


def test_reviewed_memories_say_so() -> None:
    text = format_memories(
        result(retrieved("Lives in Pune.", status=MemoryStatus.ACTIVE)), timezone_name="UTC"
    )

    assert "reviewed]" in text and "not yet reviewed" not in text


def test_nothing_found_tells_the_model_not_to_guess() -> None:
    assert "rather than guessing" in format_memories(result(), timezone_name="UTC")


def test_a_degraded_search_is_flagged() -> None:
    text = format_memories(result(retrieved("x y z"), degraded=True), timezone_name="UTC")

    assert text.endswith(
        "(Search by meaning was unavailable; these were found by words and names.)"
    )


# --- The tool ----------------------------------------------------------------------------


async def test_the_tool_searches_the_signed_in_user_s_memories_only() -> None:
    engine = FakeEngine(result(retrieved("Lives in Pune.")))
    context = turn()

    output = await SearchMemoriesTool(engine).run({"query": "Priya", "limit": 3}, context)  # type: ignore[arg-type]

    [(query, call_context)] = engine.queries
    assert (query.text, query.owner_id, query.limit) == ("Priya", context.principal.id, 3)
    # Sensitive memories never reach the model (ADR-044).
    assert query.filters.include_sensitive is False
    assert (call_context.origin, call_context.user_id) == (
        LlmCallOrigin.RETRIEVAL,
        context.principal.id,
    )
    assert output.is_error is False
    assert "Lives in Pune." in output.content


@pytest.mark.parametrize(
    "arguments", [{}, {"query": ""}, {"query": "x", "limit": 50}, {"query": "x", "extra": 1}]
)
async def test_invalid_input_is_reported_to_the_model(arguments: dict[str, Any]) -> None:
    engine = FakeEngine(result())

    output = await SearchMemoriesTool(engine).run(arguments, turn())  # type: ignore[arg-type]

    assert output.is_error is True
    assert engine.queries == []


async def test_a_query_of_spaces_is_refused_by_the_engine_s_rules() -> None:
    output = await SearchMemoriesTool(FakeEngine(result())).run({"query": "   "}, turn())  # type: ignore[arg-type]

    assert output.is_error is True


def test_the_toolbox_offers_memory_search_in_chats_and_scheduled_runs() -> None:
    toolbox = AssistantToolbox(
        connections=AsyncMock(),
        composio=None,
        browser=None,
        browser_timeout_seconds=60,
        memories=FakeEngine(result()),  # type: ignore[arg-type]
    )

    assert [tool.definition.name for tool in toolbox.for_chat()] == [
        "propose_schedule",
        "search_memories",
    ]
    assert [tool.definition.name for tool in toolbox.for_schedule()] == ["search_memories"]
    assert toolbox.capabilities.memories is True
