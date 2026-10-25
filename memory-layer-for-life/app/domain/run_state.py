"""Processing run state machine and retry policy.

Legal transitions::

    queued        -> running
    running       -> succeeded       terminal
    running       -> needs_review    replay can requeue
    running       -> failed          replay can requeue
    running       -> queued          bounded retry, or lease expiry
    failed        -> queued          explicit replay only
    needs_review  -> queued          explicit replay only

A succeeded run is never executed again. Reprocessing under a new configuration creates
a new run with a new processing identity.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from app.domain.enums import ProcessingStatus
from app.domain.errors import IllegalRunTransitionError

_TRANSITIONS: Final[Mapping[ProcessingStatus, frozenset[ProcessingStatus]]] = {
    ProcessingStatus.QUEUED: frozenset({ProcessingStatus.RUNNING}),
    ProcessingStatus.RUNNING: frozenset(
        {
            ProcessingStatus.SUCCEEDED,
            ProcessingStatus.NEEDS_REVIEW,
            ProcessingStatus.FAILED,
            ProcessingStatus.QUEUED,
        }
    ),
    ProcessingStatus.FAILED: frozenset({ProcessingStatus.QUEUED}),
    ProcessingStatus.NEEDS_REVIEW: frozenset({ProcessingStatus.QUEUED}),
    ProcessingStatus.SUCCEEDED: frozenset(),
}

# States in which a run is neither waiting for a worker nor held by one.
SETTLED_STATUSES: Final = frozenset(
    {ProcessingStatus.SUCCEEDED, ProcessingStatus.NEEDS_REVIEW, ProcessingStatus.FAILED}
)


def can_transition(current: ProcessingStatus, target: ProcessingStatus) -> bool:
    return target in _TRANSITIONS[current]


def ensure_transition(current: ProcessingStatus, target: ProcessingStatus) -> None:
    """Raise ``IllegalRunTransitionError`` unless ``current -> target`` is allowed."""
    if not can_transition(current, target):
        raise IllegalRunTransitionError(
            f"A processing run cannot move from '{current.value}' to '{target.value}'."
        )


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential backoff for transient failures.

    ``max_attempts`` counts every execution of a run, including the first. The delay
    is deterministic: a single-user pipeline gains nothing from jitter, and predictable
    scheduling keeps recovery behavior testable.
    """

    max_attempts: int = 3
    base_delay_seconds: float = 30.0
    max_delay_seconds: float = 900.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")

    def allows_retry_after(self, attempt_number: int) -> bool:
        """Whether another attempt may follow the attempt with this number."""
        return attempt_number < self.max_attempts

    def delay_after(self, attempt_number: int) -> timedelta:
        """Wait before the attempt that follows ``attempt_number``."""
        if attempt_number < 1:
            raise ValueError("attempt_number starts at 1")
        delay = self.base_delay_seconds * (2 ** (attempt_number - 1))
        return timedelta(seconds=min(delay, self.max_delay_seconds))
