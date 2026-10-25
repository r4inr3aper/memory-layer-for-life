"""Schedules: the API, manual runs, and the dispatcher, against PostgreSQL."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import LlmOperation, ScheduleRunStatus, ScheduleRunTrigger
from app.domain.errors import AssistantModelError
from app.integrations.assistant.base import UserText
from app.models.scheduled_task_run import ScheduledTaskRun
from app.repositories.schedule_repository import ScheduleRepository
from tests.integration.conftest import AssistantHarness
from tests.support.app_api import (
    API,
    confirmed_schedule,
    connect_app,
    disconnect_in_composio,
    main_thread,
    run_now,
)
from tests.support.assistant import call, new_principal, say


async def schedule_of(
    harness: AssistantHarness, headers: dict[str, str], schedule_id: str
) -> dict[str, Any]:
    response = await harness.client.get(f"{API}/schedules/{schedule_id}", headers=headers)
    assert response.status_code == 200, response.text
    schedule: dict[str, Any] = response.json()
    return schedule


# --- Listing and status ----------------------------------------------------------------


async def test_schedules_are_listed_with_their_run_counts(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)

    listing = await assistant_api.client.get(f"{API}/schedules", headers=headers)

    body = listing.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert (item["id"], item["run_count"], item["last_run_at"]) == (schedule["id"], 0, None)
    assert (item["frequency"], item["local_time"], item["timezone"]) == ("daily", "08:00", "UTC")


async def test_pausing_and_resuming_moves_the_next_slot_forward(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    path = f"{API}/schedules/{schedule['id']}"

    paused = await assistant_api.client.patch(path, json={"status": "paused"}, headers=headers)
    assistant_api.clock.advance(days=3)
    resumed = await assistant_api.client.patch(path, json={"status": "active"}, headers=headers)

    assert paused.json()["status"] == "paused"
    assert resumed.json()["status"] == "active"
    # Three days later it is 2026-10-04 12:00 UTC; slots missed while paused are skipped.
    assert resumed.json()["next_run_at"].startswith("2026-10-05T08:00:00")


async def test_cancelling_is_final(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    path = f"{API}/schedules/{schedule['id']}"

    cancelled = await assistant_api.client.patch(
        path, json={"status": "cancelled"}, headers=headers
    )
    revived = await assistant_api.client.patch(path, json={"status": "active"}, headers=headers)
    run = await assistant_api.client.post(f"{path}/runs", headers=headers)

    assert (cancelled.json()["status"], cancelled.json()["next_run_at"]) == ("cancelled", None)
    assert revived.status_code == 422
    assert revived.json()["error_code"] == "INVALID_SCHEDULE"
    assert run.status_code == 422


async def test_another_user_s_schedule_reads_as_missing(assistant_api: AssistantHarness) -> None:
    owner = assistant_api.sign_in(new_principal("Owner"))
    stranger = assistant_api.sign_in(new_principal("Stranger"))
    schedule = await confirmed_schedule(assistant_api, owner)
    path = f"{API}/schedules/{schedule['id']}"

    assert (await assistant_api.client.get(path, headers=stranger)).status_code == 404
    patched = await assistant_api.client.patch(path, json={"status": "paused"}, headers=stranger)
    assert patched.status_code == 404
    assert (await assistant_api.client.post(f"{path}/runs", headers=stranger)).status_code == 404


# --- Manual runs -----------------------------------------------------------------------


async def test_a_manual_run_posts_its_result_to_the_thread_it_came_from(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    assistant_api.model.script(say("1. Story one. 2. Story two. 3. Story three."))

    run = await run_now(assistant_api, headers, schedule["id"])

    assert (run["status"], run["trigger"], run["error_code"]) == ("succeeded", "manual", None)
    assert run["summary"] == "1. Story one. 2. Story two. 3. Story three."
    request = assistant_api.model.requests[-1]
    assert request.request.operation is LlmOperation.SCHEDULED_TASK
    assert request.transcript == (UserText(schedule["task"]),)
    assert "propose_schedule" not in [tool.name for tool in request.request.tools]
    assert "Deliver the result to: chat." in request.request.context

    thread_id = await main_thread(assistant_api, headers)
    messages = (
        await assistant_api.client.get(f"{API}/threads/{thread_id}/messages", headers=headers)
    ).json()["items"]
    delivered = messages[-1]
    assert delivered["id"] == run["chat_message_id"]
    assert delivered["content"] == (
        "Scheduled task complete: Morning news\n\n1. Story one. 2. Story two. 3. Story three."
    )
    assert delivered["metadata"]["scheduled_run"] == {
        "scheduled_task_id": schedule["id"],
        "run_id": run["id"],
        "status": "succeeded",
    }
    after = await schedule_of(assistant_api, headers, schedule["id"])
    assert (after["run_count"], after["last_run_status"]) == (1, "succeeded")
    assert after["next_run_at"] == schedule["next_run_at"]


async def test_a_failed_run_is_recorded_and_reported_in_chat(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    assistant_api.model.script(AssistantModelError("The Anthropic API could not be reached."))

    run = await run_now(assistant_api, headers, schedule["id"])

    assert (run["status"], run["error_code"]) == ("failed", "ASSISTANT_MODEL_FAILED")
    after = await schedule_of(assistant_api, headers, schedule["id"])
    assert after["last_run_error"] == "The Anthropic API could not be reached."
    thread_id = await main_thread(assistant_api, headers)
    messages = (
        await assistant_api.client.get(f"{API}/threads/{thread_id}/messages", headers=headers)
    ).json()["items"]
    assert messages[-1]["content"].startswith("Scheduled task failed: Morning news")


async def test_one_run_at_a_time_per_schedule(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    assistant_api.model.gate = asyncio.Event()
    assistant_api.model.script(say("done"))
    path = f"{API}/schedules/{schedule['id']}/runs"

    first = await assistant_api.client.post(path, headers=headers)
    second = await assistant_api.client.post(path, headers=headers)
    assistant_api.model.gate.set()
    await assistant_api.container.background.wait()

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error_code"] == "SCHEDULE_RUN_IN_PROGRESS"


async def test_a_run_delivered_to_chat_can_read_the_user_s_connected_apps(
    assistant_api: AssistantHarness,
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    assistant_api.composio.add_account(principal.id, "gmail")
    await assistant_api.client.get(f"{API}/tools/gmail/connection", headers=headers)
    schedule = await confirmed_schedule(assistant_api, headers)
    assistant_api.model.script(
        call("run_app_tool", {"app": "gmail", "tool_slug": "GMAIL_FETCH_EMAILS", "arguments": {}}),
        say("You have no unread email."),
    )

    run = await run_now(assistant_api, headers, schedule["id"])

    assert run["status"] == "succeeded", run
    request = assistant_api.model.requests[-2].request
    assert "Connected apps: Gmail." in request.context
    assert "Deliver the result to: chat." in request.context
    assert {"find_app_tools", "run_app_tool"} <= {tool.name for tool in request.tools}
    # Reading an app is allowed when the result goes to chat.
    assert [slug for _, slug, _ in assistant_api.composio.executions] == ["GMAIL_FETCH_EMAILS"]


async def test_a_run_whose_app_was_disconnected_fails_without_calling_the_model(
    assistant_api: AssistantHarness,
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    await connect_app(assistant_api, principal.id, headers, "slack")
    schedule = await confirmed_schedule(
        assistant_api, headers, delivery="slack", delivery_target="#general"
    )
    disconnect_in_composio(assistant_api, "slack")
    calls_before = len(assistant_api.model.requests)

    run = await run_now(assistant_api, headers, schedule["id"])

    assert (run["status"], run["error_code"]) == ("failed", "SCHEDULE_DELIVERY_FAILED")
    assert run["error_message"] == "Connect Slack so this schedule can deliver to it."
    assert run["chat_message_id"] is None
    assert len(assistant_api.model.requests) == calls_before


async def test_delivery_to_a_connected_app_goes_through_its_tool(
    assistant_api: AssistantHarness,
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    await connect_app(assistant_api, principal.id, headers, "slack")
    schedule = await confirmed_schedule(
        assistant_api, headers, delivery="slack", delivery_target="#general"
    )
    assistant_api.model.script(
        call(
            "run_app_tool",
            {
                "app": "slack",
                "tool_slug": "SLACK_SEND_MESSAGE",
                "arguments": {"channel": "#general", "text": "Today's AI news ..."},
            },
        ),
        say("Sent today's AI news to #general."),
    )

    run = await run_now(assistant_api, headers, schedule["id"])

    assert run["status"] == "succeeded", run
    assert run["summary"] == "Sent today's AI news to #general."
    assert [slug for _, slug, _ in assistant_api.composio.executions] == ["SLACK_SEND_MESSAGE"]
    assert "Deliver the result to: Slack (#general)." in (
        assistant_api.model.requests[-1].request.context
    )


async def test_a_run_that_never_delivers_fails_but_keeps_what_the_model_said(
    assistant_api: AssistantHarness,
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    await connect_app(assistant_api, principal.id, headers, "slack")
    schedule = await confirmed_schedule(assistant_api, headers, delivery="slack")
    assistant_api.model.script(say("I could not find the channel."))

    run = await run_now(assistant_api, headers, schedule["id"])

    assert (run["status"], run["error_code"]) == ("failed", "SCHEDULE_DELIVERY_FAILED")
    assert run["error_message"] == "The result was not delivered to Slack."
    assert run["summary"] == "I could not find the channel."


# --- Dispatcher ------------------------------------------------------------------------


async def test_a_due_slot_runs_once_and_the_schedule_moves_on(
    assistant_api: AssistantHarness,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    assistant_api.clock.advance(hours=20, seconds=30)  # 2026-10-02 08:00:30 UTC
    assistant_api.model.script(say("news"))

    executed = await assistant_api.container.schedule_dispatcher.run_due()
    again = await assistant_api.container.schedule_dispatcher.run_due()

    assert len(executed) == 1
    assert again == []
    async with session_factory() as session:
        run = await ScheduleRepository(session).get_run_by_id(executed[0])
    assert run is not None
    assert (run.trigger, run.status) == ("schedule", "succeeded")
    assert run.scheduled_for == datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
    after = await schedule_of(assistant_api, headers, schedule["id"])
    assert after["next_run_at"].startswith("2026-10-03T08:00:00")


async def test_concurrent_dispatchers_run_a_slot_once(
    assistant_api: AssistantHarness,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers = assistant_api.sign_in(new_principal())
    await confirmed_schedule(assistant_api, headers)
    assistant_api.clock.advance(hours=20, seconds=30)  # the 08:00 slot is due
    assistant_api.model.script(say("news"))
    dispatcher = assistant_api.container.schedule_dispatcher

    results = await asyncio.gather(dispatcher.run_due(), dispatcher.run_due(), dispatcher.run_due())

    assert sum(len(result) for result in results) == 1
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(ScheduledTaskRun))
    assert count == 1


async def test_a_slot_found_a_little_late_still_runs(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    assistant_api.clock.advance(hours=20, minutes=45)  # 08:45, within the hour's grace
    assistant_api.model.script(say("news"))

    executed = await assistant_api.container.schedule_dispatcher.run_due()

    assert len(executed) == 1
    after = await schedule_of(assistant_api, headers, schedule["id"])
    assert after["next_run_at"].startswith("2026-10-03T08:00:00")


async def test_a_slot_missed_by_too_much_is_skipped_and_recorded(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    calls_before = len(assistant_api.model.requests)
    assistant_api.clock.advance(days=4)  # 2026-10-05 12:00 UTC; four slots passed

    executed = await assistant_api.container.schedule_dispatcher.run_due()

    # A morning brief at noon four days later helps nobody: nothing runs, and the history
    # says why. The missed days are one entry, not four.
    assert executed == []
    assert len(assistant_api.model.requests) == calls_before
    runs = (
        await assistant_api.client.get(f"{API}/schedules/{schedule['id']}/runs", headers=headers)
    ).json()["items"]
    [skipped] = runs
    assert (skipped["status"], skipped["error_code"]) == ("skipped", "SCHEDULE_SLOT_MISSED")
    assert skipped["scheduled_for"].startswith("2026-10-02T08:00:00")
    after = await schedule_of(assistant_api, headers, schedule["id"])
    assert after["next_run_at"].startswith("2026-10-06T08:00:00")
    assert (after["run_count"], after["last_run_status"]) == (0, "skipped")
    activity = (await assistant_api.client.get(f"{API}/activity", headers=headers)).json()
    assert activity["total"] == 0


async def test_paused_schedules_are_not_dispatched(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    await assistant_api.client.patch(
        f"{API}/schedules/{schedule['id']}", json={"status": "paused"}, headers=headers
    )
    assistant_api.clock.advance(days=2)

    assert await assistant_api.container.schedule_dispatcher.run_due() == []


async def test_a_run_whose_process_stopped_is_marked_interrupted(
    assistant_api: AssistantHarness,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    abandoned = new_uuid()
    async with transaction(session_factory) as session:
        session.add(
            ScheduledTaskRun(
                id=abandoned,
                scheduled_task_id=uuid.UUID(schedule["id"]),
                trigger=ScheduleRunTrigger.MANUAL.value,
                status=ScheduleRunStatus.RUNNING.value,
                started_at=assistant_api.clock(),
                created_at=assistant_api.clock(),
            )
        )
    assistant_api.clock.advance(hours=1)

    await assistant_api.container.schedule_dispatcher.run_due()

    run = await assistant_api.client.get(
        f"{API}/schedules/{schedule['id']}/runs/{abandoned}", headers=headers
    )
    assert (run.json()["status"], run.json()["error_code"]) == (
        "failed",
        "SCHEDULE_RUN_INTERRUPTED",
    )
    after = await schedule_of(assistant_api, headers, schedule["id"])
    assert after["last_run_status"] == "failed"


async def test_runs_are_listed_newest_first(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    assistant_api.model.script(say("first"), say("second"))
    first = await run_now(assistant_api, headers, schedule["id"])
    assistant_api.clock.advance(minutes=5)
    second = await run_now(assistant_api, headers, schedule["id"])

    listing = await assistant_api.client.get(
        f"{API}/schedules/{schedule['id']}/runs", headers=headers
    )

    assert [item["id"] for item in listing.json()["items"]] == [second["id"], first["id"]]


# --- Schedules the user writes ---------------------------------------------------------

NEW_SCHEDULE: dict[str, Any] = {
    "title": "  Water the plants  ",
    "task": "Remind me to water the plants.",
    "frequency": "daily",
    "local_time": "07:30",
    "timezone": "Europe/Lisbon",
}


async def test_a_schedule_can_be_created_from_the_form(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())

    response = await assistant_api.client.post(
        f"{API}/schedules", json=NEW_SCHEDULE, headers=headers
    )

    assert response.status_code == 201, response.text
    schedule = response.json()
    assert (schedule["title"], schedule["status"], schedule["delivery"]) == (
        "Water the plants",
        "active",
        "chat",
    )
    assert (schedule["source_thread_id"], schedule["run_count"]) == (None, 0)
    # 07:30 in Lisbon (UTC+1 in October) is 06:30 UTC; at 12:00 UTC it is tomorrow's.
    assert schedule["next_run_at"].startswith("2026-10-02T06:30:00")


async def test_a_weekly_schedule_runs_on_its_weekday(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())

    response = await assistant_api.client.post(
        f"{API}/schedules",
        json={**NEW_SCHEDULE, "frequency": "weekly", "weekdays": ["monday"], "timezone": "UTC"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    # 1 October 2026 is a Thursday; the next Monday is the 5th.
    assert response.json()["next_run_at"].startswith("2026-10-05T07:30:00")


@pytest.mark.parametrize(
    ("changes", "error_code"),
    [
        ({"frequency": "weekly"}, "INVALID_SCHEDULE"),
        ({"weekdays": ["monday"]}, "INVALID_SCHEDULE"),
        ({"frequency": "monthly"}, "INVALID_SCHEDULE"),
        ({"frequency": "once"}, "INVALID_SCHEDULE"),
        ({"frequency": "once", "start_date": "2026-09-30"}, "INVALID_SCHEDULE"),
        ({"day_of_month": 40, "frequency": "monthly"}, "VALIDATION_ERROR"),
        ({"interval_hours": 30, "frequency": "interval"}, "VALIDATION_ERROR"),
        ({"weekdays": []}, "VALIDATION_ERROR"),
        ({"weekday": "monday"}, "VALIDATION_ERROR"),
        ({"delivery": "slack"}, "INVALID_SCHEDULE"),
        ({"local_time": "25:00"}, "INVALID_SCHEDULE"),
        ({"title": "   "}, "VALIDATION_ERROR"),
        ({"task": ""}, "VALIDATION_ERROR"),
        ({"timezone": "Mars/Base"}, "VALIDATION_ERROR"),
        ({"delivery": "fax"}, "VALIDATION_ERROR"),
    ],
)
async def test_an_invalid_schedule_is_refused(
    assistant_api: AssistantHarness, changes: dict[str, object], error_code: str
) -> None:
    headers = assistant_api.sign_in(new_principal())

    response = await assistant_api.client.post(
        f"{API}/schedules", json={**NEW_SCHEDULE, **changes}, headers=headers
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == error_code
    listing = await assistant_api.client.get(f"{API}/schedules", headers=headers)
    assert listing.json()["total"] == 0


async def test_a_created_schedule_posts_its_results_to_the_main_thread(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    created = await assistant_api.client.post(
        f"{API}/schedules", json=NEW_SCHEDULE, headers=headers
    )
    assistant_api.model.script(say("Time to water the plants."))

    run = await run_now(assistant_api, headers, created.json()["id"])

    thread_id = await main_thread(assistant_api, headers)
    messages = (
        await assistant_api.client.get(f"{API}/threads/{thread_id}/messages", headers=headers)
    ).json()["items"]
    assert messages[-1]["id"] == run["chat_message_id"]
    assert messages[-1]["content"].startswith("Scheduled task complete: Water the plants")


# --- Activity --------------------------------------------------------------------------


async def test_activity_lists_finished_runs_newest_first_with_where_they_went(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    assistant_api.model.script(say("First result."))
    first = await run_now(assistant_api, headers, schedule["id"])
    assistant_api.clock.advance(minutes=1)
    assistant_api.model.script(AssistantModelError("The Anthropic API could not be reached."))
    second = await run_now(assistant_api, headers, schedule["id"])
    stranger = assistant_api.sign_in(new_principal("Stranger"))

    activity = (await assistant_api.client.get(f"{API}/activity", headers=headers)).json()
    other = (await assistant_api.client.get(f"{API}/activity", headers=stranger)).json()

    thread_id = await main_thread(assistant_api, headers)
    assert activity["total"] == 2
    newest, oldest = activity["items"]
    assert (newest["run_id"], newest["status"], newest["summary"]) == (
        second["id"],
        "failed",
        None,
    )
    assert newest["error_message"] == "The Anthropic API could not be reached."
    assert (oldest["run_id"], oldest["status"], oldest["summary"]) == (
        first["id"],
        "succeeded",
        "First result.",
    )
    assert (oldest["title"], oldest["trigger"], oldest["delivery"]) == (
        "Morning news",
        "manual",
        "chat",
    )
    assert (oldest["thread_id"], oldest["chat_message_id"]) == (
        thread_id,
        first["chat_message_id"],
    )
    assert other["total"] == 0


async def test_activity_leaves_out_runs_still_running(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    assistant_api.model.gate = asyncio.Event()
    assistant_api.model.script(say("Later."))

    started = await assistant_api.client.post(
        f"{API}/schedules/{schedule['id']}/runs", headers=headers
    )
    while len(assistant_api.model.requests) < 3:  # two for the proposal, one for the run
        await asyncio.sleep(0.01)
    during = (await assistant_api.client.get(f"{API}/activity", headers=headers)).json()
    assistant_api.model.gate.set()
    await assistant_api.container.background.wait()
    after = (await assistant_api.client.get(f"{API}/activity", headers=headers)).json()

    assert started.status_code == 202
    assert during["total"] == 0
    assert after["total"] == 1
