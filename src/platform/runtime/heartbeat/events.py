"""Heartbeat event — immutable data emitted by each worker every tick."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HeartbeatEvent:
    """Immutable snapshot of worker health at a point in time.

    Attributes:
        worker_id: Unique identifier for the emitting worker.
        timestamp: Monotonic or UTC timestamp when the event was created.
        active_job_id: The job being processed, or ``None`` if idle.
        cycles_completed: Total cycles this worker has completed since start.
        health: Health classification — one of ``"ok"``, ``"idle"``, ``"busy"``.
    """

    worker_id: str
    timestamp: float
    active_job_id: str | None
    cycles_completed: int
    health: str  # "ok", "idle", "busy"
