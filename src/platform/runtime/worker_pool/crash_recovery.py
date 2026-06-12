"""Worker crash recovery — pure logic for Stratum-4.

Detects worker crashes, produces restart/requeue decisions, and returns
immutable instructions for the Control Plane (S4.7) to act on.
No IO, no persistence, no queue operations.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerCrashEvent:
    """Immutable snapshot of a worker crash.

    Attributes:
        worker_id: Identifier of the crashed worker.
        active_job_id: The job the worker was processing, or ``None``.
        timestamp: When the crash was detected.
    """

    worker_id: str
    active_job_id: str | None
    timestamp: float


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerRestartDecision:
    """Whether and why a worker should be restarted.

    Attributes:
        should_restart: ``True`` when a crashed worker must be replaced.
        worker_id: The worker to restart.
        reason: Human-readable explanation.
    """

    should_restart: bool
    worker_id: str
    reason: str


@dataclass(frozen=True)
class JobRequeueDecision:
    """Whether and why an in-flight job should be requeued.

    Attributes:
        should_requeue: ``True`` when the job must be re-enqueued.
        job_id: The job to requeue, or ``None`` if none was active.
        reason: Human-readable explanation.
    """

    should_requeue: bool
    job_id: str | None
    reason: str | None


@dataclass(frozen=True)
class WorkerPoolInstruction:
    """Aggregate instruction returned after a worker crash evaluation.

    Attributes:
        restart: Decision about restarting the worker.
        requeue: Decision about requeueing the in-flight job.
    """

    restart: WorkerRestartDecision
    requeue: JobRequeueDecision


# ---------------------------------------------------------------------------
# Crash recovery logic
# ---------------------------------------------------------------------------


class WorkerCrashRecovery:
    """Evaluates a crash event and produces deterministic restart/requeue decisions.

    Pure logic — no IO, no state mutation, no side effects.

    Args:
        clock: Optional no-arg callable for timestamps (defaults to
            :func:`time.time`). Inject a deterministic clock in tests.
    """

    def __init__(
        self,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock = clock if clock is not None else time.time

    def evaluate(self, event: WorkerCrashEvent) -> WorkerPoolInstruction:
        """Evaluate a crash event and produce restart/requeue decisions.

        Rules (pure deterministic):
        1. If worker crashed → always restart the worker.
        2. If ``active_job_id`` is set → requeue the job.
        3. Otherwise → no requeue needed.

        Args:
            event: The crash event to evaluate.

        Returns:
            A :class:`WorkerPoolInstruction` with restart and requeue decisions.
        """
        restart = WorkerRestartDecision(
            should_restart=True,
            worker_id=event.worker_id,
            reason="worker-crashed",
        )

        if event.active_job_id is not None:
            requeue = JobRequeueDecision(
                should_requeue=True,
                job_id=event.active_job_id,
                reason="job-in-flight-at-crash",
            )
        else:
            requeue = JobRequeueDecision(
                should_requeue=False,
                job_id=None,
                reason="no-active-job",
            )

        return WorkerPoolInstruction(restart=restart, requeue=requeue)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def default_worker_crash_recovery() -> WorkerCrashRecovery:
    """Create a :class:`WorkerCrashRecovery` with default settings.

    Returns:
        A ready-to-use ``WorkerCrashRecovery`` instance.
    """
    return WorkerCrashRecovery()
