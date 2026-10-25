"""Insights from the user's own memories, feedback on them, and the operator's measure of
their usefulness, against PostgreSQL."""

from app.domain.enums import EntityType, MemoryState, MemoryType
from tests.integration.conftest import AssistantHarness
from tests.support.app_api import API
from tests.support.extraction import evidence, extraction, financial, memory, mention
from tests.support.memories_api import MEMORIES, get_json, post_json, remembered, sign_up

INSIGHTS = f"{API}/me/insights"


def spent(content: str, amount: float, category: str) -> object:
    return extraction(
        memory(
            content,
            memory_type=MemoryType.FINANCIAL_NOTE,
            state=MemoryState.NOT_APPLICABLE,
            evidence_refs=[evidence(0, "x")],
            financial=financial(amount, currency="INR", category=category),
        )
    )


def about(content: str, name: str) -> object:
    return extraction(
        memory(
            content,
            memory_type=MemoryType.SEMANTIC_FACT,
            evidence_refs=[evidence(0, "x")],
            mention_indexes=[0],
        ),
        mentions=[mention(name, entity_type=EntityType.PERSON)],
    )


def todo(content: str) -> object:
    return extraction(
        memory(content, memory_type=MemoryType.TASK, evidence_refs=[evidence(0, "x")])
    )


async def test_insights_rest_on_the_user_s_memories_and_feedback_hides_them(
    assistant_api: AssistantHarness,
) -> None:
    principal, headers = await sign_up(assistant_api)
    for message, output in [
        ("lunch was 400", spent("Spent 400 on lunch", 400, "food")),
        ("petrol 600", spent("Spent 600 on petrol", 600, "fuel")),
        ("priya called today", about("Priya called.", "Priya")),
        ("priya visits sunday", about("Priya visits on Sunday.", "Priya")),
    ]:
        await remembered(assistant_api, principal, message, output)  # type: ignore[arg-type]
    tasks = [
        await remembered(assistant_api, principal, f"task number {n}", todo(f"Task {n}"))  # type: ignore[arg-type]
        for n in range(3)
    ]
    await post_json(assistant_api, f"{MEMORIES}/{tasks[0]}/complete", headers)
    await post_json(assistant_api, f"{MEMORIES}/{tasks[1]}/complete", headers)
    await post_json(assistant_api, f"{MEMORIES}/{tasks[2]}/drop", headers)
    _, stranger = await sign_up(assistant_api, "Eve")

    found = {
        item["kind"]: item for item in (await get_json(assistant_api, INSIGHTS, headers))["items"]
    }

    assert set(found) == {"money", "people.top", "follow_through"}
    assert found["money"]["title"] == "INR 1,000 noted this month"
    assert len(found["money"]["memory_ids"]) == 2
    assert found["people.top"]["target"] == "person"
    assert found["follow_through"]["title"] == "You finish 67% of what you plan"
    assert (await get_json(assistant_api, INSIGHTS, stranger))["items"] == []

    money_key = found["money"]["key"]
    await post_json(
        assistant_api,
        f"{INSIGHTS}/feedback",
        headers,
        {"key": money_key, "kind": "money", "useful": False},
        status=204,
    )
    await post_json(
        assistant_api,
        f"{INSIGHTS}/feedback",
        headers,
        {"key": found["people.top"]["key"], "kind": "people.top", "useful": True},
        status=204,
    )

    after = {item["kind"] for item in (await get_json(assistant_api, INSIGHTS, headers))["items"]}
    assert after == {"people.top", "follow_through"}

    usefulness = await get_json(assistant_api, f"{API}/console/insights/usefulness", headers)
    assert usefulness == [
        {"kind": "money", "useful": 0, "not_useful": 1},
        {"kind": "people.top", "useful": 1, "not_useful": 0},
    ]


async def test_changing_one_s_mind_replaces_the_feedback(assistant_api: AssistantHarness) -> None:
    principal, headers = await sign_up(assistant_api)
    await remembered(assistant_api, principal, "lunch was 400", spent("Lunch 400", 400, "food"))  # type: ignore[arg-type]
    [insight] = (await get_json(assistant_api, INSIGHTS, headers))["items"]

    for useful in (False, True):
        await post_json(
            assistant_api,
            f"{INSIGHTS}/feedback",
            headers,
            {"key": insight["key"], "kind": "money", "useful": useful},
            status=204,
        )

    assert [
        item["key"] for item in (await get_json(assistant_api, INSIGHTS, headers))["items"]
    ] == [insight["key"]]
