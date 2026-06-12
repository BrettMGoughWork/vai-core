"""Worker tick — per-cycle decision logic for Stratum-4.

S4.5.3: The tick orchestrates scheduling (selecting the next job) from within
the worker loop.  The actual polling/claiming/execution is added in S4.6–S4.7.

S4.5.4: The tick also emits heartbeat events on each cycle so that the
control plane can track worker liveness.
"""

from __future__ import annotations

from src.platform.runtime.heartbeat.emitter import HeartbeatEmitter
from src.platform.runtime.heartbeat.events import HeartbeatEvent
from src.platform.runtime.scheduling.policy import (
    JobMetadata,
    Scheduler,
    SchedulingContext,
    SchedulingDecision,
    SchedulingMode,
    create_scheduler,
)


class TickInstruction:
    """Pure-data instruction returned by a single worker tick.

    Attributes:
        action: Machine-readable action name (``"no_work"``, ``"claim_job"``,
            ``"heartbeat"``).
        job_id: The job to claim, or ``None`` if no work is available.
        reason: Human-readable explanation.
        event: Attached :class:`HeartbeatEvent` when action is ``"heartbeat"``.
    """

    def __init__(
        self,
        action: str,
        job_id: str | None,
        reason: str | None,
        event: HeartbeatEvent | None = None,
    ) -> None:
        self.action = action
        self.job_id = job_id
        self.reason = reason
        self.event = event

    @staticmethod
    def no_work(reason: str | None = None) -> "TickInstruction":
        """Returned when there is no work available."""
        return TickInstruction(action="no_work", job_id=None, reason=reason)

    @staticmethod
    def claim_job(job_id: str, reason: str | None = None) -> "TickInstruction":
        """Returned when a job has been selected and should be claimed."""
        return TickInstruction(action="claim_job", job_id=job_id, reason=reason)

    @staticmethod
    def heartbeat(event: HeartbeatEvent) -> "TickInstruction":
        """Returned to emit a heartbeat event for the current tick."""
        return TickInstruction(
            action="heartbeat",
            job_id=event.active_job_id,
            reason="heartbeat",
            event=event,
        )


def run_heartbeat_tick(
    emitter: HeartbeatEmitter,
    active_job_id: str | None,
    cycles_completed: int,
    health: str,
) -> TickInstruction:
    """Execute one heartbeat tick: emit a heartbeat event for a worker.

    Args:
        emitter: A configured :class:`HeartbeatEmitter` instance.
        active_job_id: Job currently being processed, or ``None``.
        cycles_completed: Cumulative cycles completed by this worker.
        health: ``"ok"``, ``"idle"``, or ``"busy"``.

    Returns:
        A :class:`TickInstruction` with action ``"heartbeat"`` and the
        attached :class:`HeartbeatEvent`.
    """
    event = emitter.emit(
        active_job_id=active_job_id,
        cycles_completed=cycles_completed,
        health=health,
    )
    return TickInstruction.heartbeat(event)


def run_scheduling_tick(
    scheduler: Scheduler,
    pending_jobs: list[JobMetadata],
) -> TickInstruction:
    """Execute one scheduling tick: select the next job from *pending_jobs*.

    Args:
        scheduler: A configured :class:`Scheduler` instance.
        pending_jobs: Snapshot of currently eligible jobs.

    Returns:
        A :class:`TickInstruction` directing the worker to either claim a
        specific job or report no work.
    """
    ctx = SchedulingContext(pending_jobs=pending_jobs)
    decision: SchedulingDecision = scheduler.select(ctx)

    if decision.job_id is None:
        return TickInstruction.no_work(reason=decision.reason)

    return TickInstruction.claim_job(job_id=decision.job_id, reason=decision.reason)
