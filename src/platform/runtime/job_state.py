"""Job State Machine v1 — Stratum-4 runtime.

Strict, validated state transitions for the Job lifecycle.
Pure (no side effects), deterministic, and isolated from S1/S2/S3.

Allowed transitions::

    pending → running → succeeded
                      ↘  failed
                      ↘  poison  (terminal)
"""

from __future__ import annotations

from enum import Enum


class JobState(str, Enum):
    """Lifecycle states for a ``Job`` inside Stratum-4.

    Six states total: ``PENDING``, ``RUNNING``, ``SUCCEEDED``, ``FAILED``,
    and ``POISON``.  ``POISON`` is a terminal state for jobs that have
    exceeded the maximum consecutive failure threshold and must not be
    retried.

    Values are lowercase strings for stable JSON serialisation.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    POISON = "poison"


# Allowed transitions expressed as a set of (current, target) pairs.
_TRANSITIONS: set[tuple[JobState, JobState]] = {
    (JobState.PENDING, JobState.RUNNING),
    (JobState.RUNNING, JobState.SUCCEEDED),
    (JobState.RUNNING, JobState.FAILED),
    (JobState.RUNNING, JobState.POISON),
    # Terminal — no outgoing transitions from SUCCEEDED, FAILED, or POISON.
}


def can_transition(current: JobState, target: JobState) -> bool:
    """Return ``True`` if the ``current → target`` transition is allowed."""
    return (current, target) in _TRANSITIONS


def assert_transition(current: JobState, target: JobState) -> None:
    """Raise ``ValueError`` if the ``current → target`` transition is illegal.

    Safe to inline in hot paths — the check is an O(1) set lookup.
    """
    if not can_transition(current, target):
        raise ValueError(
            f"Illegal job state transition: {current.value} → {target.value}"
        )


def transition(current: JobState, target: JobState) -> JobState:
    """Transition from ``current`` to ``target``, or raise ``ValueError``.

    Args:
        current: The current state.
        target:  The desired next state.

    Returns:
        ``target`` if the transition is allowed.

    Raises:
        ValueError: If the transition is not in the allowed set.
    """
    assert_transition(current, target)
    return target
