"""Heartbeat monitor — tracks worker liveness on the control plane side.

Pure logic: records last-seen timestamps and computes health status
without any IO, persistence, or transport.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.platform.runtime.heartbeat.events import HeartbeatEvent


@dataclass(frozen=True)
class HeartbeatStatus:
    """Health status for a single worker at a point in time.

    Attributes:
        worker_id: The worker being evaluated.
        last_seen: Timestamp of the most recent heartbeat.
        is_healthy: ``True`` if the worker is within the timeout window.
        reason: Human-readable explanation of the health decision.
    """

    worker_id: str
    last_seen: float
    is_healthy: bool
    reason: str | None


class HeartbeatMonitor:
    """Tracks worker liveness from incoming heartbeat events.

    The monitor is deterministic — given the same sequence of events and
    the same clock, it always produces the same status.

    Args:
        timeout_seconds: Maximum age (in seconds) before a worker is
            considered unhealthy.
    """

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout = timeout_seconds
        self.last_seen: dict[str, float] = {}

    def update(
        self, event: HeartbeatEvent, now: float | None = None
    ) -> HeartbeatStatus:
        """Record a heartbeat and return the worker's current health status.

        Args:
            event: The incoming heartbeat event.
            now: Optional current time (defaults to ``event.timestamp``).

        Returns:
            A :class:`HeartbeatStatus` reflecting the worker's health.
        """
        self.last_seen[event.worker_id] = event.timestamp
        reference = now if now is not None else event.timestamp
        elapsed = reference - event.timestamp
        is_healthy = elapsed <= self.timeout
        return HeartbeatStatus(
            worker_id=event.worker_id,
            last_seen=event.timestamp,
            is_healthy=is_healthy,
            reason=(
                "ok"
                if is_healthy
                else f"last_seen {elapsed:.1f}s ago (timeout {self.timeout}s)"
            ),
        )

    def evaluate(self, now: float) -> list[HeartbeatStatus]:
        """Return health status for all known workers at *now*.

        Args:
            now: Current timestamp for liveness evaluation.

        Returns:
            A list of :class:`HeartbeatStatus`, one per known worker.
        """
        results: list[HeartbeatStatus] = []
        for worker_id, last in self.last_seen.items():
            elapsed = now - last
            is_healthy = elapsed <= self.timeout
            results.append(
                HeartbeatStatus(
                    worker_id=worker_id,
                    last_seen=last,
                    is_healthy=is_healthy,
                    reason=(
                        "ok"
                        if is_healthy
                        else f"last_seen {elapsed:.1f}s ago (timeout {self.timeout}s)"
                    ),
                )
            )
        return results
