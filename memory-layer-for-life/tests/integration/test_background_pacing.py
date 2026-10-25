"""When each background loop next has work, against PostgreSQL. The loops use it to
sleep until then when the database should sleep too (app.services.pacing).

The test clock starts on Thursday 2026-10-01 at 12:00 UTC (17:30 in Kolkata).
"""

from datetime import UTC, datetime, timedelta

from app.db.session import transaction
from app.repositories.processing_run_repository import ProcessingRunRepository
from tests.integration.conftest import AssistantHarness, AssistantHarnessFactory, HarnessFactory
from tests.support.app_api import API
from tests.support.assistant import new_principal
from tests.support.extraction import ScriptedExtractor
from tests.support.pipeline import FakeClock


async def test_the_scheduler_knows_its_next_slot(assistant_api: AssistantHarness) -> None:
    dispatcher = assistant_api.container.schedule_dispatcher
    headers = assistant_api.sign_in(new_principal())

    assert await dispatcher.next_due() is None

    created = await assistant_api.client.post(
        f"{API}/schedules",
        json={
            "title": "Plants",
            "task": "Water them.",
            "frequency": "daily",
            "local_time": "09:00",
            "timezone": "UTC",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert await dispatcher.next_due() == datetime(2026, 10, 2, 9, 0, tzinfo=UTC)

    paused = await assistant_api.client.patch(
        f"{API}/schedules/{created.json()['id']}", json={"status": "paused"}, headers=headers
    )
    assert paused.status_code == 200, paused.text
    assert await dispatcher.next_due() is None


async def test_reminders_and_briefs_set_when_the_proactive_loop_wakes(
    assistant_api: AssistantHarness,
) -> None:
    dispatcher = assistant_api.container.proactive_dispatcher
    headers = assistant_api.sign_in(new_principal())

    assert await dispatcher.next_due() is None

    remind_at = assistant_api.clock() + timedelta(hours=2)
    written = await assistant_api.client.post(
        f"{API}/me/memories",
        json={"memory_type": "task", "content": "Call Mum", "remind_at": remind_at.isoformat()},
        headers=headers,
    )
    assert written.status_code == 201, written.text
    assert await dispatcher.next_due() == remind_at

    # A brief at 18:00 in Kolkata (12:30 UTC) comes before the reminder.
    me = await assistant_api.client.patch(
        f"{API}/me",
        json={"timezone": "Asia/Kolkata", "brief_enabled": True, "brief_time": "18:00"},
        headers=headers,
    )
    assert me.status_code == 200, me.text
    assert await dispatcher.next_due() == datetime(2026, 10, 1, 12, 30, tzinfo=UTC)


async def test_the_pipeline_knows_when_a_run_is_due_or_a_lease_ends(
    make_harness: HarnessFactory, clock: FakeClock
) -> None:
    harness = make_harness(ScriptedExtractor())

    assert await harness.runner.next_due() is None

    unit = await harness.ingest("buy milk")
    assert await harness.runner.next_due() == clock()

    # Claimed but never finished: due again when its lease (600 s) ends.
    async with transaction(harness.session_factory) as session:
        assert await ProcessingRunRepository(session).claim(unit.run.id, now=clock())
    assert await harness.runner.next_due() == clock() + timedelta(seconds=600)


async def test_signed_in_requests_mark_activity_and_health_checks_do_not(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    """An uptime monitor pinging /health keeps a free host awake without waking the loops
    (and so the database); someone using the app restores their normal pace."""
    async with assistant_api_with(BACKGROUND_IDLE_INTERVAL_SECONDS=3600.0) as api:
        pacer = api.container.pacer
        assert pacer.saves_database is True

        health = await api.client.get(f"{API}/health/live")
        assert health.status_code == 200
        assert pacer.is_active() is False

        me = await api.client.get(f"{API}/me", headers=api.sign_in(new_principal()))
        assert me.status_code == 200, me.text
        assert pacer.is_active() is True


async def test_an_always_on_database_paces_as_before(assistant_api: AssistantHarness) -> None:
    pacer = assistant_api.container.pacer

    await assistant_api.client.get(f"{API}/me", headers=assistant_api.sign_in(new_principal()))

    assert pacer.saves_database is False
    assert pacer.delay(60) == 60
