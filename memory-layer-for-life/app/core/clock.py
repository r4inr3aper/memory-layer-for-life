"""Time source. Injected wherever behavior depends on the current time, so tests control it."""

from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Timezone-aware current time. All persisted timestamps are UTC."""
    return datetime.now(UTC)
