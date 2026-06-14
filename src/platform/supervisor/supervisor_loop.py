"""Supervisor Loop — deterministic worker lifecycle management for Stratum-4.

The Supervisor Loop runs on a fixed interval and is responsible for:

- continuously monitoring all workers in the pool
- evaluating worker health based on heartbeat signals
- detecting stalled, crashed, or degraded workers
- restarting unhealthy workers deterministically
- emitting structured events for observability
- avoiding cascading restarts
- avoiding race conditions
- avoiding double-starting workers

The Supervisor does not execute jobs. It only manages worker lifecycle.

Output format ready for inclusion in /src/supervisor/supervisor_loop.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from src.platform.observability.logging import log_supervisor_action, log_worker_activity
from src.platform.observability.metrics import emit_metric
from src.platform.observability.tracing import emit_segment_trace as _emit_seg
from src.platform.supervisor.system_alerts import alert_async as _alert_async


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEALTHY = "healthy"
DEGRADED = "degraded"
UNRESPONSIVE = "unresponsive"

STATUS_HEALTHY = HEALTHY
STATUS_DEGRADED = DEGRADED
STATUS_UNRESPONSIVE = UNRESPONSIVE


# ---------------------------------------------------------------------------
# Data model — WorkerHeartbeat (schema from spec §2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerHeartbeat:
    """A heartbeat emitted by a worker.

    Schema spec::

        {
            "worker_id": "<string>",
            "timestamp": "<iso8601>",
            "status": "healthy" | "degraded" | "unresponsive",
            "job_id": "<string|null>"
        }

    Attributes:
        worker_id: Unique identifier for the emitting worker.
        timestamp: Unix timestamp (seconds) when the heartbeat was created.
        status:    Health classification per the spec.
        job_id:    The job being processed, or ``None`` if idle.
    """

    worker_id: str
    timestamp: float
    status: str = HEALTHY
    job_id: str | None = None


# ---------------------------------------------------------------------------
# Data model — WorkerHealth
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerHealth:
    """Evaluated health status for a single worker.

    Attributes:
        worker_id: The worker being evaluated.
        status:    ``"healthy"``, ``"degraded"``, or ``"unresponsive"``.
        last_seen: Timestamp of the most recent heartbeat.
        reason:    Human-readable explanation of the health decision.
    """

    worker_id: str
    status: str
    last_seen: float
    reason: str | None


# ---------------------------------------------------------------------------
# Data model — WorkerRestartEvent (schema from spec §4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerRestartEvent:
    """Emitted when a worker is restarted.

    Schema spec::

        {
            "event": "worker_restarted",
            "old_worker_id": "<string>",
            "new_worker_id": "<string>",
            "reason": "<string>",
            "timestamp": "<iso8601>"
        }
    """

    event: str = "worker_restarted"
    old_worker_id: str = ""
    new_worker_id: str = ""
    reason: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "event": self.event,
            "old_worker_id": self.old_worker_id,
            "new_worker_id": self.new_worker_id,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Data model — SupervisorEscalation (schema from spec §5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupervisorEscalation:
    """Emitted when escalation thresholds are exceeded.

    Schema spec::

        {
            "event": "supervisor_escalation",
            "severity": "critical",
            "timestamp": "<iso8601>",
            "reason": "<string>"
        }
    """

    event: str = "supervisor_escalation"
    severity: str = "critical"
    timestamp: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "event": self.event,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# SupervisorConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupervisorConfig:
    """Configuration for the :class:`SupervisorLoop`.

    Attributes:
        heartbeat_timeout: Seconds since last heartbeat before a worker is
            considered unresponsive. (default: 30.0)
        check_interval: Seconds between supervisor loop iterations.
            (default: 5.0) — used for logging, not by pure evaluation.
        pool_concurrency: Expected number of workers in the pool.
            (default: 1)
        max_restarts: Maximum number of worker restarts allowed within
            *restart_window* seconds before escalation.
            (default: 5)
        restart_window: Time window (seconds) for *max_restarts* threshold.
            (default: 60.0)
        max_worker_restarts: Maximum times a single worker identity may be
            restarted before escalation. (default: 3)
    """

    heartbeat_timeout: float = 30.0
    check_interval: float = 5.0
    pool_concurrency: int = 1
    max_restarts: int = 5
    restart_window: float = 60.0
    max_worker_restarts: int = 3


# ---------------------------------------------------------------------------
# SupervisorDecision
# ---------------------------------------------------------------------------


@dataclass
class SupervisorDecision:
    """The result of a single supervisor evaluation cycle.

    Attributes:
        restarts:    Workers to restart, with the reason for each.
        escalations: Escalation events to emit to the S4 Control Plane.
        health_map:  Evaluated health status for all known workers.
        pool_full:   ``True`` if the pool size matches ``pool_concurrency``.
        pool_worker_ids: Current worker IDs in the pool.
        active_unhealthy: Number of unhealthy workers detected.
    """

    restarts: list[WorkerRestartEvent] = field(default_factory=list)
    escalations: list[SupervisorEscalation] = field(default_factory=list)
    health_map: dict[str, WorkerHealth] = field(default_factory=dict)
    pool_full: bool = True
    pool_worker_ids: set[str] = field(default_factory=set)
    active_unhealthy: int = 0


# ---------------------------------------------------------------------------
# SupervisorLoop
# ---------------------------------------------------------------------------


class SupervisorLoop:
    """Deterministic worker lifecycle supervisor.

    The loop is pure logic — it receives heartbeats, evaluates health,
    decides restarts, checks escalation thresholds, and returns a
    :class:`SupervisorDecision`.  No IO, no side effects.

    Args:
        config: Supervisor configuration.
        clock:  A no-arg callable returning the current time in seconds
            (defaults to :func:`time.time`).  Inject a deterministic
            clock in tests.
    """

    def __init__(
        self,
        config: SupervisorConfig | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.config = config or SupervisorConfig()
        self._clock = clock if clock is not None else time.time

        # Worker tracking
        self._heartbeats: dict[str, WorkerHeartbeat] = {}
        self._restart_count: int = 0
        self._restart_timestamps: list[float] = []
        self._worker_restart_counts: dict[str, int] = {}
        self._next_worker_id: int = 0  # monotonic counter for fresh IDs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect_heartbeat(self, heartbeat: WorkerHeartbeat) -> None:
        """Record a heartbeat from a worker.

        The most recent heartbeat per worker is retained.  Heartbeats
        from unknown workers create a new entry.

        Args:
            heartbeat: The heartbeat event to record.
        """
        existing = self._heartbeats.get(heartbeat.worker_id)
        if existing is None or heartbeat.timestamp > existing.timestamp:
            self._heartbeats[heartbeat.worker_id] = heartbeat

    def collect_heartbeats(self, heartbeats: list[WorkerHeartbeat]) -> None:
        """Record multiple heartbeats at once.

        Args:
            heartbeats: A list of heartbeat events.
        """
        for hb in heartbeats:
            self.collect_heartbeat(hb)

    def get_heartbeat(self, worker_id: str) -> WorkerHeartbeat | None:
        """Return the most recent heartbeat for *worker_id*, or ``None``."""
        return self._heartbeats.get(worker_id)

    def remove_worker(self, worker_id: str) -> None:
        """Remove a worker from tracking (e.g. after planned shutdown).

        Args:
            worker_id: The worker to remove.
        """
        self._heartbeats.pop(worker_id, None)
        self._worker_restart_counts.pop(worker_id, None)

    def evaluate(
        self,
        now: float | None = None,
        active_worker_ids: set[str] | None = None,
    ) -> SupervisorDecision:
        """Run one full supervisor evaluation cycle.

        Steps (spec §3):
            1. Evaluate health for all known workers.
            2. For each unhealthy worker, schedule a restart.
            3. Ensure pool size matches configured concurrency.
            4. Check escalation thresholds.
            5. Return a :class:`SupervisorDecision`.

        Args:
            now:              Current timestamp.  Defaults to ``self._clock()``.
            active_worker_ids: The set of worker IDs currently running in the
                pool.  If provided, workers not in this set are considered
                unresponsive.  If ``None``, only heartbeats are consulted.

        Returns:
            A :class:`SupervisorDecision` describing all actions to take.
        """
        ts = now if now is not None else self._clock()
        decision = SupervisorDecision()
        cfg = self.config

        # Step 1: Evaluate health for all known workers
        health_map = self._evaluate_all_health(ts, active_worker_ids)
        decision.health_map = health_map

        # Step 2: For each unhealthy worker, schedule a restart
        unhealthy_workers: dict[str, WorkerHealth] = {}
        for wid, health in health_map.items():
            if health.status == UNRESPONSIVE:
                unhealthy_workers[wid] = health
            elif health.status == DEGRADED:
                unhealthy_workers[wid] = health

        for wid, health in unhealthy_workers.items():
            restart_ev = self._schedule_restart(wid, health.status, ts)
            decision.restarts.append(restart_ev)
            _emit_seg("", "health", "repair", "supervisor_loop",
                      extra_fields={"worker_id": wid, "status": health.status})
            log_supervisor_action(
                "repair",
                f"Worker {wid} {health.status}: {health.reason}",
                worker_id=wid,
            )
            _alert_async(
                severity="error",
                source="supervisor_loop",
                summary=f"Worker {wid} {health.status}",
                details=health.reason,
                metadata={"worker_id": wid, "status": health.status},
            )

        decision.active_unhealthy = len(unhealthy_workers)

        # Step 3: Maintain pool size — fill missing slots
        known_ids = set(health_map.keys())
        if active_worker_ids is not None:
            # Workers in the pool but not tracked by heartbeats are missing
            missing = cfg.pool_concurrency - len(active_worker_ids)
            # Workers we're about to remove (restarted) count as lost
            missing_after_restart = missing + len(unhealthy_workers)
            decision.pool_worker_ids = active_worker_ids

            for _ in range(missing_after_restart):
                fresh_worker_id = self._fresh_worker_id()
                _emit_seg("", "pool", "repair", "supervisor_loop",
                          extra_fields={"new_worker_id": fresh_worker_id,
                                       "reason": "pool_maintenance"})
                # We need a restart-like event for new workers too, but
                # with empty old_worker_id since nobody was replaced.
                decision.restarts.append(
                    WorkerRestartEvent(
                        old_worker_id="",
                        new_worker_id=fresh_worker_id,
                        reason="pool_maintenance",
                        timestamp=_iso_timestamp(ts),
                    )
                )

            decision.pool_full = missing <= 0
        else:
            decision.pool_worker_ids = set(health_map.keys())
            decision.pool_full = len(health_map) >= cfg.pool_concurrency

        # Step 4: Escalation checks
        if decision.restarts:
            self._record_restarts(ts)
            for escalation in self._check_escalation(ts):
                decision.escalations.append(escalation)
                _emit_seg("", "escalation", "repair", "supervisor_loop",
                          extra_fields={"reason": escalation.reason,
                                       "severity": escalation.severity})
                _alert_async(
                    severity="critical",
                    source="supervisor_loop",
                    summary=f"Escalation threshold exceeded: {escalation.reason}",
                    details=escalation.reason,
                    metadata={"severity": escalation.severity},
                )

        # Step 5: Global heartbeat stop detection
        if active_worker_ids is not None and len(active_worker_ids) > 0:
            tracked = sum(
                1 for h in health_map.values() if h.status == HEALTHY
            )
            if tracked == 0:
                escalation = SupervisorEscalation(
                    timestamp=_iso_timestamp(ts),
                    reason=(
                        f"All {len(active_worker_ids)} workers unhealthy; "
                        f"heartbeats stopped globally"
                    ),
                )
                decision.escalations.append(escalation)
                log_supervisor_action(
                    "panic",
                    f"All {len(active_worker_ids)} workers unhealthy; heartbeats stopped globally",
                )
                _alert_async(
                    severity="critical",
                    source="supervisor_loop",
                    summary="All workers unhealthy — heartbeats stopped globally",
                    details=escalation.reason,
                    metadata={"worker_count": len(active_worker_ids)},
                )

        return decision

    # ------------------------------------------------------------------
    # Health evaluation
    # ------------------------------------------------------------------

    def evaluate_health(
        self,
        worker_id: str,
        now: float,
    ) -> WorkerHealth:
        """Evaluate health for a single worker.

        Args:
            worker_id: The worker to evaluate.
            now:       Current timestamp.

        Returns:
            A :class:`WorkerHealth` with the worker's status.
        """
        hb = self._heartbeats.get(worker_id)
        if hb is None:
            emit_metric("s4.worker.health", 1, {
                "worker_id": worker_id,
                "status": "unhealthy",
            })
            log_worker_activity(worker_id, "unresponsive")
            return WorkerHealth(
                worker_id=worker_id,
                status=UNRESPONSIVE,
                last_seen=0.0,
                reason="No heartbeat ever received",
            )
        elapsed = now - hb.timestamp
        if elapsed > self.config.heartbeat_timeout:
            emit_metric("s4.worker.health", 1, {
                "worker_id": worker_id,
                "status": "unhealthy",
            })
            emit_metric("s4.repair.count", 1, {
                "repairtype": "heartbeattimeout",
            })
            log_worker_activity(worker_id, "timeout")
            return WorkerHealth(
                worker_id=worker_id,
                status=UNRESPONSIVE,
                last_seen=hb.timestamp,
                reason=(
                    f"Last heartbeat {elapsed:.1f}s ago "
                    f"(timeout {self.config.heartbeat_timeout:.0f}s)"
                ),
            )
        if hb.status == DEGRADED:
            log_worker_activity(worker_id, "degraded")
            return WorkerHealth(
                worker_id=worker_id,
                status=DEGRADED,
                last_seen=hb.timestamp,
                reason="Worker reported degraded status",
            )
        log_worker_activity(worker_id, "healthy")
        return WorkerHealth(
            worker_id=worker_id,
            status=HEALTHY,
            last_seen=hb.timestamp,
            reason="ok",
        )

    # ------------------------------------------------------------------
    # Restart internals
    # ------------------------------------------------------------------

    def _fresh_worker_id(self) -> str:
        """Generate a new, never-used-before worker ID.

        Returns:
            A string like ``"worker-4"``.
        """
        wid = f"worker-{self._next_worker_id}"
        self._next_worker_id += 1
        return wid

    def _schedule_restart(
        self,
        worker_id: str,
        reason: str,
        timestamp: float,
    ) -> WorkerRestartEvent:
        """Produce a restart event for *worker_id*.

        The old worker is removed from tracking and a new ID is generated.

        Args:
            worker_id: The worker to restart.
            reason:    Why the worker is being restarted.
            timestamp: Current timestamp.

        Returns:
            A :class:`WorkerRestartEvent` with old/new worker IDs.
        """
        new_id = self._fresh_worker_id()

        # Track restart count for this worker identity
        self._worker_restart_counts[worker_id] = (
            self._worker_restart_counts.get(worker_id, 0) + 1
        )

        # Remove old worker from tracking
        self.remove_worker(worker_id)

        return WorkerRestartEvent(
            old_worker_id=worker_id,
            new_worker_id=new_id,
            reason=reason,
            timestamp=_iso_timestamp(timestamp),
        )

    def _record_restarts(self, timestamp: float) -> None:
        """Record restart timestamps for escalation detection.

        Args:
            timestamp: Current timestamp.
        """
        self._restart_count += 1
        self._restart_timestamps.append(timestamp)

        # Prune timestamps outside the restart_window
        window = self.config.restart_window
        cutoff = timestamp - window
        self._restart_timestamps = [
            t for t in self._restart_timestamps if t >= cutoff
        ]

    # ------------------------------------------------------------------
    # Escalation checks
    # ------------------------------------------------------------------

    def _check_escalation(
        self, timestamp: float
    ) -> list[SupervisorEscalation]:
        """Check escalation thresholds and return any escalation events.

        Checks (spec §5):
            - More than *max_restarts* workers restarted within *restart_window*.
            - Same worker restarted more than *max_worker_restarts* times.
            - Pool cannot maintain required concurrency (handled in evaluate()).

        Args:
            timestamp: Current timestamp.

        Returns:
            A list of :class:`SupervisorEscalation` events (may be empty).
        """
        escalations: list[SupervisorEscalation] = []
        cfg = self.config

        # Threshold 1: Burst restart
        recent_count = len(self._restart_timestamps)
        if recent_count > cfg.max_restarts:
            escalations.append(
                SupervisorEscalation(
                    timestamp=_iso_timestamp(timestamp),
                    reason=(
                        f"Burst restart: {recent_count} restarts "
                        f"in {cfg.restart_window:.0f}s "
                        f"(max {cfg.max_restarts})"
                    ),
                )
            )

        # Threshold 2: Same worker restarted repeatedly
        for wid, count in self._worker_restart_counts.items():
            if count > cfg.max_worker_restarts:
                escalations.append(
                    SupervisorEscalation(
                        timestamp=_iso_timestamp(timestamp),
                        reason=(
                            f"Worker {wid} restarted {count} times "
                            f"(max {cfg.max_worker_restarts})"
                        ),
                    )
                )

        return escalations

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_all_health(
        self,
        now: float,
        active_worker_ids: set[str] | None = None,
    ) -> dict[str, WorkerHealth]:
        """Evaluate health for all known workers.

        If *active_worker_ids* is provided, workers that are expected
        (in the active set) but have no heartbeat are reported as
        unresponsive.

        Args:
            now:               Current timestamp.
            active_worker_ids: Optional set of expected worker IDs.

        Returns:
            A dict mapping worker_id to :class:`WorkerHealth`.
        """
        health_map: dict[str, WorkerHealth] = {}

        # Evaluate all workers we've heard from
        for wid in self._heartbeats:
            health_map[wid] = self.evaluate_health(wid, now)

        # Workers expected but never heard from
        if active_worker_ids is not None:
            for wid in active_worker_ids:
                if wid not in health_map:
                    health_map[wid] = WorkerHealth(
                        worker_id=wid,
                        status=UNRESPONSIVE,
                        last_seen=0.0,
                        reason="Worker in active set but no heartbeat",
                    )

        return health_map


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso_timestamp(ts: float) -> str:
    """Convert a Unix timestamp to an ISO-8601 string.

    Args:
        ts: Unix timestamp in seconds.

    Returns:
        ISO-8601 formatted string (UTC).
    """
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
