"""Scheduling v2 against PostgreSQL: one-time, weekday, monthly, and interval schedules;
editing and deleting; skipping late or overlapping slots; and Cooper's proposals.

The test clock starts on Thursday 2026-10-01 at 12:00 UTC.
"""

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import transaction
from app.integrations.assistant.base import ToolResults
from app.models.chat_message import ChatMessage
from tests.integration.conftest import AssistantHarness
from tests.support.app_api import (
    API,
    confirmed_schedule,
    connect_app,
    main_thread,
    run_now,
    stream,
)
from tests.support.assistant import call, new_principal, say

BASE: dict[str, Any] = {
    "title": "Plants",
    "task": "Remind me to water the plants.",
    "local_time": "09:00",
    "timezone": "UTC",
}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]


async def create(harness: AssistantHarness, headers: dict[str, str], **fields: Any) -> Any:
    response = await harness.client.post(
        f"{API}/schedules", json={**BASE, **fields}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def edit(
    harness: AssistantHarness, headers: dict[str, str], schedule_id: str, **fields: Any
) -> Any:
    return await harness.client.patch(
        f"{API}/schedules/{schedule_id}", json=fields, headers=headers
    )


async def schedule_of(harness: AssistantHarness, headers: dict[str, str], schedule_id: str) -> Any:
    response = await harness.client.get(f"{API}/schedules/{schedule_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def runs_of(harness: AssistantHarness, headers: dict[str, str], schedule_id: str) -> Any:
    response = await harness.client.get(f"{API}/schedules/{schedule_id}/runs", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


# --- Kinds of schedule -----------------------------------------------------------------


async def test_a_one_time_reminder_runs_on_its_date_in_its_timezone(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())

    schedule = await create(
        assistant_api,
        headers,
        frequency="once",
        start_date="2026-10-03",
        local_time="07:30",
        timezone="Asia/Kolkata",
    )

    assert (schedule["frequency"], schedule["start_date"], schedule["weekdays"]) == (
        "once",
        "2026-10-03",
        [],
    )
    assert schedule["next_run_at"].startswith("2026-10-03T02:00:00")
    assert (schedule["next_run_local"], schedule["timezone"]) == (
        "2026-10-03T07:30",
        "Asia/Kolkata",
    )


async def test_weekdays_run_monday_to_friday(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())

    schedule = await create(
        assistant_api, headers, frequency="weekly", weekdays=["friday", *WEEKDAYS[:4]]
    )

    assert schedule["weekdays"] == WEEKDAYS
    assert schedule["next_run_at"].startswith("2026-10-02T09:00:00")  # Friday


async def test_a_monthly_schedule_on_the_31st_runs_on_a_shorter_month_s_last_day(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(assistant_api, headers, frequency="monthly", day_of_month=31)
    assert schedule["next_run_at"].startswith("2026-10-31T09:00:00")
    assistant_api.clock.advance(days=30, hours=-3, seconds=30)  # 2026-10-31 09:00:30
    assistant_api.model.script(say("Water them."))

    await assistant_api.container.schedule_dispatcher.run_due()

    after = await schedule_of(assistant_api, headers, schedule["id"])
    assert after["next_run_at"].startswith("2026-11-30T09:00:00")  # November has 30 days


async def test_an_interval_runs_every_few_hours_from_its_first_time(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(
        assistant_api, headers, frequency="interval", interval_hours=4, local_time="13:00"
    )
    # Without a date it starts today.
    assert (schedule["start_date"], schedule["interval_hours"]) == ("2026-10-01", 4)
    assert schedule["next_run_at"].startswith("2026-10-01T13:00:00")
    assistant_api.clock.advance(hours=1, seconds=10)
    assistant_api.model.script(say("Done."))

    executed = await assistant_api.container.schedule_dispatcher.run_due()

    assert len(executed) == 1
    after = await schedule_of(assistant_api, headers, schedule["id"])
    assert after["next_run_at"].startswith("2026-10-01T17:00:00")


# --- Editing ---------------------------------------------------------------------------


async def test_title_task_and_rule_can_be_edited(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(assistant_api, headers, frequency="daily")

    response = await edit(
        assistant_api,
        headers,
        schedule["id"],
        title="Plants and herbs",
        task="Remind me to water the plants and the herbs.",
        frequency="weekly",
        weekdays=["saturday", "monday"],
    )

    assert response.status_code == 200, response.text
    edited = response.json()
    assert (edited["title"], edited["task"]) == (
        "Plants and herbs",
        "Remind me to water the plants and the herbs.",
    )
    assert edited["original_prompt"] == schedule["original_prompt"]
    assert (edited["frequency"], edited["weekdays"]) == ("weekly", ["monday", "saturday"])
    assert edited["next_run_at"].startswith("2026-10-03T09:00:00")  # Saturday


async def test_changing_the_frequency_drops_fields_the_new_one_does_not_use(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(assistant_api, headers, frequency="weekly", weekdays=["monday"])

    edited = (await edit(assistant_api, headers, schedule["id"], frequency="daily")).json()

    assert (edited["frequency"], edited["weekdays"], edited["local_time"]) == ("daily", [], "09:00")
    assert edited["next_run_at"].startswith("2026-10-02T09:00:00")


async def test_changing_the_time_or_timezone_keeps_the_rest_of_the_rule(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(assistant_api, headers, frequency="weekly", weekdays=["monday"])

    edited = (
        await edit(
            assistant_api, headers, schedule["id"], local_time="18:00", timezone="Asia/Kolkata"
        )
    ).json()

    assert (edited["weekdays"], edited["timezone"]) == (["monday"], "Asia/Kolkata")
    # Monday 18:00 in Kolkata is 12:30 UTC.
    assert edited["next_run_at"].startswith("2026-10-05T12:30:00")
    assert edited["next_run_local"] == "2026-10-05T18:00"


async def test_a_finished_reminder_edited_to_a_new_date_is_active_again(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(assistant_api, headers, frequency="once", start_date="2026-10-02")
    assistant_api.clock.advance(hours=21, seconds=20)  # 2026-10-02 09:00:20
    assistant_api.model.script(say("Water them."))
    await assistant_api.container.schedule_dispatcher.run_due()
    finished = await schedule_of(assistant_api, headers, schedule["id"])

    resumed = await edit(assistant_api, headers, schedule["id"], status="active")
    rescheduled = await edit(assistant_api, headers, schedule["id"], start_date="2026-10-05")

    assert (finished["status"], finished["next_run_at"]) == ("completed", None)
    assert resumed.status_code == 422
    assert "Change its date" in resumed.json()["message"]
    assert rescheduled.status_code == 200, rescheduled.text
    assert rescheduled.json()["status"] == "active"
    assert rescheduled.json()["next_run_at"].startswith("2026-10-05T09:00:00")


async def test_a_paused_schedule_stays_paused_when_edited(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(assistant_api, headers, frequency="daily")
    await edit(assistant_api, headers, schedule["id"], status="paused")

    edited = (await edit(assistant_api, headers, schedule["id"], local_time="10:15")).json()

    assert (edited["status"], edited["local_time"]) == ("paused", "10:15")


async def test_results_can_only_be_moved_to_a_connected_app(
    assistant_api: AssistantHarness,
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    schedule = await create(assistant_api, headers, frequency="daily")

    refused = await edit(assistant_api, headers, schedule["id"], delivery="slack")
    await connect_app(assistant_api, principal.id, headers, "slack")
    moved = await edit(
        assistant_api, headers, schedule["id"], delivery="slack", delivery_target="#plants"
    )
    back = await edit(assistant_api, headers, schedule["id"], delivery="chat")

    assert refused.status_code == 422
    assert "Connect Slack" in refused.json()["message"]
    assert (moved.json()["delivery"], moved.json()["delivery_target"]) == ("slack", "#plants")
    # Chat has no target.
    assert (back.json()["delivery"], back.json()["delivery_target"]) == ("chat", None)


async def test_a_cancelled_schedule_cannot_be_edited(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(assistant_api, headers, frequency="daily")
    await edit(assistant_api, headers, schedule["id"], status="cancelled")

    renamed = await edit(assistant_api, headers, schedule["id"], title="Again")
    cancelled_again = await edit(assistant_api, headers, schedule["id"], status="cancelled")

    assert renamed.status_code == 422
    assert cancelled_again.status_code == 200


async def test_an_edit_must_change_something(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(assistant_api, headers, frequency="daily")

    response = await edit(assistant_api, headers, schedule["id"])

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


# --- Deleting --------------------------------------------------------------------------


async def test_deleting_removes_the_schedule_and_its_history_but_not_the_chat(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    assistant_api.model.script(say("Story one."))
    run = await run_now(assistant_api, headers, schedule["id"])
    path = f"{API}/schedules/{schedule['id']}"

    deleted = await assistant_api.client.delete(path, headers=headers)

    assert deleted.status_code == 204
    assert (await assistant_api.client.get(path, headers=headers)).status_code == 404
    assert (await assistant_api.client.get(f"{path}/runs", headers=headers)).status_code == 404
    activity = (await assistant_api.client.get(f"{API}/activity", headers=headers)).json()
    assert activity["total"] == 0
    thread_id = await main_thread(assistant_api, headers)
    messages = (
        await assistant_api.client.get(f"{API}/threads/{thread_id}/messages", headers=headers)
    ).json()["items"]
    assert run["chat_message_id"] in [message["id"] for message in messages]


async def test_a_running_schedule_cannot_be_deleted(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await confirmed_schedule(assistant_api, headers)
    path = f"{API}/schedules/{schedule['id']}"
    assistant_api.model.gate = asyncio.Event()
    assistant_api.model.script(say("Later."))
    await assistant_api.client.post(f"{path}/runs", headers=headers)
    while len(assistant_api.model.requests) < 3:  # two for the proposal, one for the run
        await asyncio.sleep(0.01)

    during = await assistant_api.client.delete(path, headers=headers)
    assistant_api.model.gate.set()
    await assistant_api.container.background.wait()
    after = await assistant_api.client.delete(path, headers=headers)

    assert during.status_code == 409
    assert during.json()["error_code"] == "SCHEDULE_RUN_IN_PROGRESS"
    assert after.status_code == 204


async def test_another_user_s_schedule_cannot_be_deleted(assistant_api: AssistantHarness) -> None:
    owner = assistant_api.sign_in(new_principal("Owner"))
    stranger = assistant_api.sign_in(new_principal("Stranger"))
    schedule = await create(assistant_api, owner, frequency="daily")

    response = await assistant_api.client.delete(
        f"{API}/schedules/{schedule['id']}", headers=stranger
    )

    assert response.status_code == 404
    assert (await schedule_of(assistant_api, owner, schedule["id"]))["status"] == "active"


# --- The dispatcher --------------------------------------------------------------------


async def test_a_one_time_schedule_runs_once_and_completes(assistant_api: AssistantHarness) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(assistant_api, headers, frequency="once", start_date="2026-10-02")
    assistant_api.clock.advance(hours=21, seconds=30)
    assistant_api.model.script(say("Water them."))

    first = await assistant_api.container.schedule_dispatcher.run_due()
    assistant_api.clock.advance(days=2)
    second = await assistant_api.container.schedule_dispatcher.run_due()

    assert (len(first), second) == (1, [])
    after = await schedule_of(assistant_api, headers, schedule["id"])
    assert (after["status"], after["next_run_at"], after["run_count"]) == ("completed", None, 1)


async def test_a_one_time_schedule_missed_by_too_much_is_skipped_and_completes(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(assistant_api, headers, frequency="once", start_date="2026-10-02")
    assistant_api.clock.advance(days=2)

    executed = await assistant_api.container.schedule_dispatcher.run_due()

    assert executed == []
    after = await schedule_of(assistant_api, headers, schedule["id"])
    assert (after["status"], after["last_run_status"]) == ("completed", "skipped")
    [skipped] = await runs_of(assistant_api, headers, schedule["id"])
    assert skipped["error_code"] == "SCHEDULE_SLOT_MISSED"


async def test_a_slot_due_during_a_manual_run_is_skipped_and_recorded(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(assistant_api, headers, frequency="daily", local_time="12:10")
    assistant_api.model.gate = asyncio.Event()
    assistant_api.model.script(say("Manual result."))
    await assistant_api.client.post(f"{API}/schedules/{schedule['id']}/runs", headers=headers)
    while not assistant_api.model.requests:
        await asyncio.sleep(0.01)
    assistant_api.clock.advance(minutes=10, seconds=30)  # the 12:10 slot is due

    executed = await assistant_api.container.schedule_dispatcher.run_due()
    assistant_api.model.gate.set()
    await assistant_api.container.background.wait()

    assert executed == []
    runs = await runs_of(assistant_api, headers, schedule["id"])
    statuses = {(run["trigger"], run["status"], run["error_code"]) for run in runs}
    assert statuses == {
        ("manual", "succeeded", None),
        ("schedule", "skipped", "SCHEDULE_SLOT_BUSY"),
    }
    after = await schedule_of(assistant_api, headers, schedule["id"])
    assert after["next_run_at"].startswith("2026-10-02T12:10:00")


async def test_an_interval_slot_late_by_more_than_half_its_period_is_skipped(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    schedule = await create(
        assistant_api, headers, frequency="interval", interval_hours=1, local_time="13:00"
    )
    assistant_api.clock.advance(hours=1, minutes=40)  # 13:40: 40 minutes late, period 1 hour

    executed = await assistant_api.container.schedule_dispatcher.run_due()

    assert executed == []
    after = await schedule_of(assistant_api, headers, schedule["id"])
    assert after["next_run_at"].startswith("2026-10-01T14:00:00")
    assert after["last_run_status"] == "skipped"


# --- Cooper's proposals ----------------------------------------------------------------


async def test_cooper_can_propose_weekdays_and_one_time_reminders(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())

    weekdays = await confirmed_schedule(
        assistant_api, headers, frequency="weekly", weekdays=list(reversed(WEEKDAYS))
    )
    reminder = await confirmed_schedule(
        assistant_api, headers, frequency="once", date="2026-10-03", time="07:00"
    )

    assert (weekdays["frequency"], weekdays["weekdays"]) == ("weekly", WEEKDAYS)
    assert (reminder["frequency"], reminder["start_date"], reminder["local_time"]) == (
        "once",
        "2026-10-03",
        "07:00",
    )


async def test_a_proposal_stored_before_v2_still_confirms(
    assistant_api: AssistantHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(
        call(
            "propose_schedule",
            {
                "title": "Monday news",
                "task": "Summarize the news.",
                "frequency": "weekly",
                "weekdays": ["monday"],
                "time": "09:00",
                "summary": "Every Monday.",
            },
        ),
        say("Confirm to start."),
    )
    events = await stream(assistant_api, headers, thread_id, "News every Monday")
    message_id = uuid.UUID(events[-1]["message"]["id"])
    # Rewrite the stored proposal the way it was written before weekdays became a list.
    async with transaction(session_factory) as session:
        message = await session.scalar(select(ChatMessage).where(ChatMessage.id == message_id))
        assert message is not None
        metadata = dict(message.metadata_)
        proposal = dict(metadata["schedule_proposal"])
        del proposal["weekdays"]
        proposal["weekday"] = "monday"
        metadata["schedule_proposal"] = proposal
        message.metadata_ = metadata

    confirmed = await assistant_api.client.post(
        f"{API}/threads/{thread_id}/messages/{message_id}/proposal/confirm", headers=headers
    )

    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["schedule"]["weekdays"] == ["monday"]


async def test_cooper_is_told_when_the_app_for_results_is_not_connected(
    assistant_api: AssistantHarness,
) -> None:
    headers = assistant_api.sign_in(new_principal())
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(
        call(
            "propose_schedule",
            {
                "title": "Standup",
                "task": "Post the standup notes.",
                "frequency": "daily",
                "time": "09:00",
                "delivery": "slack",
                "delivery_target": "#team",
                "summary": "Every day.",
            },
        ),
        say("Slack isn't connected yet. Want to connect it?"),
    )

    events = await stream(assistant_api, headers, thread_id, "Post standup to Slack daily")

    assert events[-1]["message"]["metadata"].get("schedule_proposal") is None
    [results] = [
        item
        for item in assistant_api.model.requests[-1].transcript
        if isinstance(item, ToolResults)
    ]
    [result] = results.results
    assert result.is_error
    assert "Slack is not connected" in result.content


async def test_confirming_needs_the_app_for_results_to_be_connected_still(
    assistant_api: AssistantHarness,
) -> None:
    principal = new_principal()
    headers = assistant_api.sign_in(principal)
    await connect_app(assistant_api, principal.id, headers, "slack")
    thread_id = await main_thread(assistant_api, headers)
    assistant_api.model.script(
        call(
            "propose_schedule",
            {
                "title": "Standup",
                "task": "Post the standup notes.",
                "frequency": "daily",
                "time": "09:00",
                "delivery": "slack",
                "delivery_target": "#team",
                "summary": "Every day.",
            },
        ),
        say("Confirm to start."),
    )
    events = await stream(assistant_api, headers, thread_id, "Post standup to Slack daily")
    message_id = events[-1]["message"]["id"]
    await assistant_api.client.delete(f"{API}/tools/slack/connection", headers=headers)

    confirmed = await assistant_api.client.post(
        f"{API}/threads/{thread_id}/messages/{message_id}/proposal/confirm", headers=headers
    )

    assert confirmed.status_code == 422
    assert "Connect Slack" in confirmed.json()["message"]
