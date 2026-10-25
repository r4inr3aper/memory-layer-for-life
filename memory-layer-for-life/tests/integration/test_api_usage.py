"""The daily prompt limit and the usage meter, against PostgreSQL.

A prompt is a chat message the user sends or a scheduled run, counted per UTC day in
``daily_usage``. The test clock starts at 2026-10-01 12:00 UTC.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from httpx import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import LlmCallOrigin
from app.domain.principal import Principal
from app.models.app_user import AppUser
from app.models.daily_usage import DailyUsage
from app.models.llm_call import LlmCall
from tests.integration.conftest import AssistantHarness, AssistantHarnessFactory
from tests.support.app_api import (
    API,
    confirmed_schedule,
    connect_app,
    disconnect_in_composio,
    main_thread,
    run_now,
    stream,
)
from tests.support.assistant import new_principal, say
from tests.support.pipeline import DEFAULT_START


async def usage(harness: AssistantHarness, headers: dict[str, str]) -> dict[str, Any]:
    response = await harness.client.get(f"{API}/me/usage", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def send(
    harness: AssistantHarness,
    headers: dict[str, str],
    thread_id: str,
    text: str,
    *,
    timezone: str = "UTC",
) -> Response:
    return await harness.client.post(
        f"{API}/threads/{thread_id}/messages",
        json={"content": text, "timezone": timezone},
        headers=headers,
    )


async def set_own_limit(
    harness: AssistantHarness,
    session_factory: async_sessionmaker[AsyncSession],
    principal: Principal,
    limit: int,
) -> None:
    await harness.client.get(f"{API}/me", headers=harness.sign_in(principal))
    async with transaction(session_factory) as session:
        await session.execute(
            update(AppUser).where(AppUser.id == principal.id).values(daily_prompt_limit=limit)
        )


def cost_row(user_id: object, *, started_at: Any, input_tokens: int, cost: str) -> LlmCall:
    return LlmCall(
        id=new_uuid(),
        provider="anthropic",
        operation="chat",
        origin="assistant",
        status="succeeded",
        requested_model="claude-haiku-5-5",
        started_at=started_at,
        duration_ms=10,
        input_tokens=input_tokens,
        output_tokens=input_tokens // 10,
        estimated_cost_usd=Decimal(cost),
        user_id=user_id,
    )


# --- The meter -------------------------------------------------------------------------


async def test_the_meter_counts_today_s_prompts_and_model_use(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    schedule = await confirmed_schedule(assistant_api, headers)  # one message
    assistant_api.model.script(say("Result."))
    await run_now(assistant_api, headers, schedule["id"])  # one run
    other = new_principal("Other")
    await assistant_api.client.get(f"{API}/me", headers=assistant_api.sign_in(other))
    async with transaction(session_factory) as session:
        session.add_all(
            [
                cost_row(principal.id, started_at=DEFAULT_START, input_tokens=1000, cost="0.01"),
                cost_row(principal.id, started_at=DEFAULT_START, input_tokens=500, cost="0.02"),
                # Yesterday's, and another user's, do not count.
                cost_row(
                    principal.id,
                    started_at=DEFAULT_START - timedelta(hours=13),
                    input_tokens=9999,
                    cost="9",
                ),
                cost_row(other.id, started_at=DEFAULT_START, input_tokens=9999, cost="9"),
            ]
        )

    body = await usage(assistant_api, headers)

    assert body["day"] == "2026-10-01"
    assert body["resets_at"].startswith("2026-10-02T00:00:00")
    assert (body["chat_messages"], body["scheduled_runs"], body["prompts_used"]) == (1, 1, 2)
    assert (body["prompt_limit"], body["prompts_remaining"]) == (40, 38)
    assert (body["input_tokens"], body["output_tokens"]) == (1500, 150)
    assert Decimal(body["estimated_cost_usd"]) == Decimal("0.03")
    # Shown in rupees at the configured rate (88 per dollar by default).
    assert (body["currency"], Decimal(body["estimated_cost"])) == ("INR", Decimal("2.64"))


async def test_a_new_user_has_used_nothing(assistant_api: AssistantHarness) -> None:
    body = await usage(assistant_api, assistant_api.sign_in(new_principal()))

    assert (body["prompts_used"], body["prompts_remaining"], body["estimated_cost_usd"]) == (
        0,
        40,
        None,
    )


async def test_each_day_s_prompts_are_kept_in_their_own_row(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(say("a"), say("b"), say("c"))
    await stream(assistant_api, headers, thread_id, "one")
    await stream(assistant_api, headers, thread_id, "two")
    assistant_api.clock.advance(days=1)
    await stream(assistant_api, headers, thread_id, "three")

    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(DailyUsage)
                .where(DailyUsage.user_id == principal.id)
                .order_by(DailyUsage.day)
            )
        )

    assert [(row.day, row.chat_messages, row.scheduled_runs) for row in rows] == [
        (date(2026, 10, 1), 2, 0),
        (date(2026, 10, 2), 1, 0),
    ]
    assert (await usage(assistant_api, headers))["prompts_used"] == 1


async def test_model_calls_are_attributed_to_the_user(assistant_api: AssistantHarness) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    schedule = await confirmed_schedule(assistant_api, headers)
    assistant_api.model.script(say("Result."))
    await run_now(assistant_api, headers, schedule["id"])

    contexts = [request.request.call_context for request in assistant_api.model.requests]

    assert {context.user_id for context in contexts} == {principal.id}
    assert contexts[0].origin is LlmCallOrigin.ASSISTANT
    assert contexts[-1].origin is LlmCallOrigin.SCHEDULER


# --- The daily limit -------------------------------------------------------------------


async def test_a_message_over_the_daily_limit_is_refused_until_tomorrow(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    async with assistant_api_with(ASSISTANT_DAILY_PROMPT_LIMIT=2) as harness:
        headers = harness.sign_in(new_principal())
        thread_id = await main_thread(harness, headers)
        harness.model.script(say("one"), say("two"), say("tomorrow"))
        await stream(harness, headers, thread_id, "one")
        await stream(harness, headers, thread_id, "two")

        refused = await send(harness, headers, thread_id, "three")
        meter = await usage(harness, headers)
        listing = await harness.client.get(f"{API}/threads/{thread_id}/messages", headers=headers)
        harness.clock.advance(hours=12)  # midnight UTC
        events = await stream(harness, headers, thread_id, "a new day")

    assert refused.status_code == 429
    assert refused.json()["error_code"] == "QUOTA_EXCEEDED"
    assert refused.json()["message"] == (
        "You have used today's 2 prompts. More are available after 00:00 (UTC)."
    )
    assert (meter["prompts_used"], meter["prompts_remaining"]) == (2, 0)
    assert listing.json()["total"] == 4  # nothing stored for the refused message
    assert events[-1]["type"] == "final"


async def test_the_reset_is_told_in_the_user_s_own_time(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    async with assistant_api_with(ASSISTANT_DAILY_PROMPT_LIMIT=1) as harness:
        headers = harness.sign_in(new_principal())
        thread_id = await main_thread(harness, headers)
        harness.model.script(say("one"))
        await stream(harness, headers, thread_id, "one", timezone="Asia/Kolkata")

        refused = await send(harness, headers, thread_id, "two", timezone="Asia/Kolkata")

    assert refused.json()["message"] == (
        "You have used today's 1 prompts. More are available after 05:30 (Asia/Kolkata)."
    )


async def test_a_user_s_own_limit_overrides_the_default(
    assistant_api_with: AssistantHarnessFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with assistant_api_with(ASSISTANT_DAILY_PROMPT_LIMIT=1) as harness:
        raised = new_principal("Raised")
        unlimited = new_principal("Unlimited")
        await set_own_limit(harness, session_factory, raised, 3)
        await set_own_limit(harness, session_factory, unlimited, 0)
        harness.model.script(*(say(str(number)) for number in range(7)))

        raised_headers = harness.sign_in(raised)
        raised_thread = await main_thread(harness, raised_headers)
        for number in range(3):
            await stream(harness, raised_headers, raised_thread, f"message {number}")
        refused = await send(harness, raised_headers, raised_thread, "one too many")

        unlimited_headers = harness.sign_in(unlimited)
        unlimited_thread = await main_thread(harness, unlimited_headers)
        for number in range(4):
            await stream(harness, unlimited_headers, unlimited_thread, f"message {number}")
        unlimited_meter = await usage(harness, unlimited_headers)

    assert refused.status_code == 429
    assert (unlimited_meter["prompts_used"], unlimited_meter["prompt_limit"]) == (4, None)


async def test_a_limit_of_zero_means_unlimited(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    async with assistant_api_with(ASSISTANT_DAILY_PROMPT_LIMIT=0) as harness:
        body = await usage(harness, harness.sign_in(new_principal()))

    assert (body["prompt_limit"], body["prompts_remaining"]) == (None, None)


async def test_concurrent_messages_cannot_both_take_the_last_prompt(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    async with assistant_api_with(ASSISTANT_DAILY_PROMPT_LIMIT=1) as harness:
        headers = harness.sign_in(new_principal())
        main_id = await main_thread(harness, headers)
        side = await harness.client.post(f"{API}/threads", json={}, headers=headers)
        harness.model.script(say("only one"))

        responses = await asyncio.gather(
            send(harness, headers, main_id, "first"),
            send(harness, headers, side.json()["id"], "second"),
        )
        meter = await usage(harness, headers)

    assert sorted(response.status_code for response in responses) == [200, 429]
    assert meter["prompts_used"] == 1


# --- Scheduled runs --------------------------------------------------------------------


async def test_a_scheduled_run_over_the_limit_fails_without_calling_the_model(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    async with assistant_api_with(ASSISTANT_DAILY_PROMPT_LIMIT=2) as harness:
        headers = harness.sign_in(new_principal())
        schedule = await confirmed_schedule(harness, headers)  # prompt 1
        harness.model.script(say("Result."))
        allowed = await run_now(harness, headers, schedule["id"])  # prompt 2
        requests = len(harness.model.requests)

        refused = await run_now(harness, headers, schedule["id"])
        meter = await usage(harness, headers)

    assert allowed["status"] == "succeeded"
    assert (refused["status"], refused["error_code"]) == ("failed", "QUOTA_EXCEEDED")
    assert len(harness.model.requests) == requests
    assert (meter["scheduled_runs"], meter["prompts_used"]) == (1, 2)


async def test_a_run_that_cannot_deliver_uses_no_prompt(assistant_api: AssistantHarness) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    await connect_app(assistant_api, principal.id, headers, "slack")
    created = await assistant_api.client.post(
        f"{API}/schedules",
        json={
            "title": "Standup notes",
            "task": "Post the standup notes.",
            "frequency": "daily",
            "local_time": "09:00",
            "timezone": "UTC",
            "delivery": "slack",
        },
        headers=headers,
    )
    disconnect_in_composio(assistant_api, "slack")

    run = await run_now(assistant_api, headers, created.json()["id"])

    assert run["status"] == "failed"
    assert (await usage(assistant_api, headers))["scheduled_runs"] == 0


# --- History -----------------------------------------------------------------------------


async def history(
    harness: AssistantHarness, headers: dict[str, str], granularity: str
) -> dict[str, Any]:
    response = await harness.client.get(
        f"{API}/me/usage/history?granularity={granularity}", headers=headers
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def seed_history(
    harness: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> dict[str, str]:
    """Today (Thursday 2026-10-01): two messages and $0.03. Yesterday: four prompts and
    $0.50. Tuesday 2026-09-01: $1.00. Another user: $9."""
    principal = new_principal()
    headers = harness.sign_in(principal)
    thread_id = await main_thread(harness, headers)
    harness.model.script(say("a"), say("b"))
    await stream(harness, headers, thread_id, "one")
    await stream(harness, headers, thread_id, "two")
    other = new_principal("Other")
    await harness.client.get(f"{API}/me", headers=harness.sign_in(other))
    async with transaction(session_factory) as session:
        session.add_all(
            [
                DailyUsage(
                    id=new_uuid(),
                    user_id=principal.id,
                    day=date(2026, 9, 30),
                    chat_messages=3,
                    scheduled_runs=1,
                    created_at=DEFAULT_START,
                    updated_at=DEFAULT_START,
                ),
                cost_row(principal.id, started_at=DEFAULT_START, input_tokens=100, cost="0.01"),
                cost_row(principal.id, started_at=DEFAULT_START, input_tokens=100, cost="0.02"),
                cost_row(
                    principal.id,
                    started_at=DEFAULT_START - timedelta(hours=13),
                    input_tokens=1000,
                    cost="0.5",
                ),
                cost_row(
                    principal.id,
                    started_at=DEFAULT_START - timedelta(days=30),
                    input_tokens=10,
                    cost="1",
                ),
                cost_row(other.id, started_at=DEFAULT_START, input_tokens=1, cost="9"),
            ]
        )
    return headers


def summary(period: dict[str, Any]) -> tuple[str, int, Decimal]:
    return (period["start"], period["prompts"], Decimal(period["cost_usd"]))


async def test_daily_history_covers_the_last_fourteen_days(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await seed_history(assistant_api, session_factory)

    body = await history(assistant_api, headers, "day")

    periods = body["periods"]
    assert body["granularity"] == "day"
    assert len(periods) == 14
    assert periods[0]["start"] == "2026-09-18"
    assert summary(periods[-1]) == ("2026-10-01", 2, Decimal("0.03"))
    assert summary(periods[-2]) == ("2026-09-30", 4, Decimal("0.5"))
    assert summary(periods[-3]) == ("2026-09-29", 0, Decimal("0"))
    assert periods[-2]["input_tokens"] == 1000
    # The 1 September call is older than fourteen days.
    assert (Decimal(body["total_cost_usd"]), body["total_prompts"]) == (Decimal("0.53"), 6)
    assert body["currency"] == "INR"
    assert (Decimal(periods[-1]["cost"]), Decimal(body["total_cost"])) == (
        Decimal("2.64"),
        Decimal("46.64"),
    )


async def test_weekly_history_starts_weeks_on_monday(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await seed_history(assistant_api, session_factory)

    body = await history(assistant_api, headers, "week")

    periods = body["periods"]
    assert len(periods) == 12
    assert periods[0]["start"] == "2026-07-13"
    assert summary(periods[-1]) == ("2026-09-28", 6, Decimal("0.53"))
    assert summary(periods[-5]) == ("2026-08-31", 0, Decimal("1"))


async def test_monthly_history_covers_the_last_twelve_months(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await seed_history(assistant_api, session_factory)

    body = await history(assistant_api, headers, "month")

    periods = body["periods"]
    assert len(periods) == 12
    assert periods[0]["start"] == "2025-11-01"
    assert summary(periods[-1]) == ("2026-10-01", 2, Decimal("0.03"))
    assert summary(periods[-2]) == ("2026-09-01", 4, Decimal("1.5"))
    assert (Decimal(body["total_cost_usd"]), body["total_prompts"]) == (Decimal("1.53"), 6)


async def test_a_new_user_has_an_empty_history(assistant_api: AssistantHarness) -> None:
    body = await history(assistant_api, assistant_api.sign_in(new_principal()), "day")

    assert all(summary(period)[1:] == (0, Decimal("0")) for period in body["periods"])
    assert (Decimal(body["total_cost_usd"]), body["total_prompts"]) == (Decimal("0"), 0)


async def test_an_unknown_granularity_is_refused(assistant_api: AssistantHarness) -> None:
    response = await assistant_api.client.get(
        f"{API}/me/usage/history?granularity=hour",
        headers=assistant_api.sign_in(new_principal()),
    )

    assert response.status_code == 422
