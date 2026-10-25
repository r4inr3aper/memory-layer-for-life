"""Background pacing: unchanged with an always-on database; with a scale-to-zero one,
loops keep their pace only while someone uses the app or work is queued, and otherwise
wake together on a shared tick or exactly when something is due."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.services.pacing import ALWAYS_ON, BackgroundPacer

# 2026-10-01 12:10:00 UTC: ten minutes past an hourly tick.
NOW = datetime(2026, 10, 1, 12, 10, tzinfo=UTC)
HOUR = 3600.0


class Monotonic:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def pacer(**options: object) -> tuple[BackgroundPacer, Monotonic]:
    monotonic = Monotonic()
    defaults: dict[str, object] = {
        "idle_interval": HOUR,
        "active_window": 120.0,
        "clock": lambda: NOW,
        "monotonic": monotonic,
    }
    return BackgroundPacer(**{**defaults, **options}), monotonic  # type: ignore[arg-type]


def test_an_always_on_database_keeps_every_loop_s_own_interval() -> None:
    assert ALWAYS_ON.saves_database is False
    assert ALWAYS_ON.delay(60, next_due=NOW + timedelta(hours=5)) == 60


def test_idle_loops_wait_for_the_shared_tick() -> None:
    idle, _ = pacer()

    assert idle.delay(60) == 50 * 60  # 12:10 → 13:00
    assert idle.delay(15) == 50 * 60  # every loop, whatever its interval, wakes together


def test_a_tick_closer_than_the_loop_s_interval_waits_for_the_next_one() -> None:
    idle, _ = pacer(clock=lambda: datetime(2026, 10, 1, 12, 59, 30, tzinfo=UTC))

    assert idle.delay(60) == 30 + HOUR


def test_something_due_before_the_tick_wakes_the_loop_for_it() -> None:
    idle, _ = pacer()

    assert idle.delay(60, next_due=NOW + timedelta(minutes=7)) == 7 * 60


def test_something_due_after_the_tick_waits_for_the_tick() -> None:
    idle, _ = pacer()

    assert idle.delay(60, next_due=NOW + timedelta(hours=3)) == 50 * 60


def test_an_overdue_item_never_spins_the_loop() -> None:
    """A due item that keeps failing is retried at the loop's own pace, not in a burst."""
    idle, _ = pacer()

    assert idle.delay(60, next_due=NOW - timedelta(minutes=5)) == 60


def test_someone_using_the_app_restores_the_normal_pace_for_a_while() -> None:
    idle, monotonic = pacer()
    idle.touch()

    assert idle.is_active() is True
    assert idle.delay(60) == 60

    monotonic.now += 121
    assert idle.is_active() is False
    assert idle.delay(60) == 50 * 60


def test_queued_work_keeps_the_normal_pace() -> None:
    idle, _ = pacer()

    assert idle.delay(30, busy=True) == 30


async def test_the_first_request_after_a_quiet_spell_wakes_waiting_loops() -> None:
    idle, _ = pacer()
    sleeper = asyncio.create_task(idle.sleep(60))
    await asyncio.sleep(0.01)
    assert not sleeper.done()  # waiting for 13:00

    idle.touch()

    await asyncio.wait_for(sleeper, timeout=1)


async def test_an_always_on_pacer_never_asks_when_work_is_due() -> None:
    async def query() -> datetime:
        raise AssertionError("not asked")

    assert await ALWAYS_ON.next_due(query, loop="test") is None


async def test_a_failed_due_query_only_means_waiting_for_the_tick() -> None:
    idle, _ = pacer()

    async def broken() -> datetime:
        raise ConnectionError("database asleep")

    async def due() -> datetime:
        return NOW

    assert await idle.next_due(broken, loop="test") is None
    assert await idle.next_due(due, loop="test") == NOW


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_idle_interval_means_always_on(blank: str) -> None:
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
        BACKGROUND_IDLE_INTERVAL_SECONDS=blank,
    )

    assert settings.BACKGROUND_IDLE_INTERVAL_SECONDS is None
