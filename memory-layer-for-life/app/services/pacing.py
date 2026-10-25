"""How long the background loops wait between passes.

With an always-on database (the default), each loop waits its own interval, as it always
has.

A database that scales to zero, such as Neon on its free plan, counts every minute it is
awake and suspends after five idle minutes. Loops that query it every 15 to 60 seconds
keep it awake around the clock. With ``idle_interval`` set, a loop keeps its own pace only
while someone is using the app (the database is awake for them anyway) or while it has
work queued. Otherwise every loop waits for the same wall-clock tick, or for the next
thing it knows is due (a schedule slot, a reminder, a brief, a retry), whichever comes
first. The database then sleeps in between, and nothing that is due runs late. The first
signed-in request after a quiet spell wakes every waiting loop, so what that visit creates
is picked up at once.
"""

import asyncio
import contextlib
import math
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

import structlog

from app.core.clock import Clock, utc_now

logger = structlog.get_logger(__name__)


class BackgroundPacer:
    def __init__(
        self,
        *,
        idle_interval: float | None = None,
        active_window: float = 120.0,
        clock: Clock = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._idle_interval = idle_interval
        self._active_window = active_window
        self._clock = clock
        self._monotonic = monotonic
        self._last_activity: float | None = None
        self._wake = asyncio.Event()

    @property
    def saves_database(self) -> bool:
        """Whether loops wait for ticks and due times when nobody is using the app."""
        return self._idle_interval is not None

    def touch(self) -> None:
        """Someone is using the app. After a quiet spell, waiting loops wake at once."""
        if not self.saves_database:
            return
        was_quiet = not self.is_active()
        self._last_activity = self._monotonic()
        if was_quiet:
            self._wake.set()
            self._wake = asyncio.Event()

    def is_active(self) -> bool:
        return (
            self._last_activity is not None
            and self._monotonic() - self._last_activity < self._active_window
        )

    def delay(
        self, interval: float, *, next_due: datetime | None = None, busy: bool = False
    ) -> float:
        """Seconds a loop with this interval waits before its next pass.

        While idle: until the next shared tick, or until ``next_due`` if that is sooner,
        but never less than the loop's own interval, so a due item that keeps failing
        cannot spin the loop.
        """
        if self._idle_interval is None or busy or self.is_active():
            return interval
        now = self._clock()
        tick = self._idle_interval - (now.timestamp() % self._idle_interval)
        if tick < interval:
            tick += self._idle_interval
        due = math.inf
        if next_due is not None:
            due = max((next_due - now).total_seconds(), interval)
        return min(tick, due)

    async def next_due(
        self, query: Callable[[], Awaitable[datetime | None]], *, loop: str
    ) -> datetime | None:
        """A loop's next due time, asked only when it matters: when the database may
        sleep. A failed query only means waiting for the next tick."""
        if not self.saves_database:
            return None
        try:
            return await query()
        except Exception:
            logger.exception("background_next_due_failed", loop=loop)
            return None

    async def sleep(
        self, interval: float, *, next_due: datetime | None = None, busy: bool = False
    ) -> None:
        if self._idle_interval is None or busy or self.is_active():
            await asyncio.sleep(interval)
            return
        wake = self._wake
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(wake.wait(), timeout=self.delay(interval, next_due=next_due))


# Loops built without a pacer behave as they always have.
ALWAYS_ON = BackgroundPacer()
