"""Health Checks v1 — Stratum-4 liveness, readiness, and worker pool health.

Provides three deterministic, non-blocking, transport-agnostic check
functions:

- ``check_liveness()``          — Is the S4 daemon running and responsive?
- ``check_readiness()``         — Can S4 accept and process new jobs right now?
- ``check_worker_pool_health()`` — Is the worker pool healthy?

Runtime components register themselves via the ``init_health`` /
``register_*`` API at startup.  If no component is registered the
corresponding check returns ``"unhealthy"`` with a clear explanation.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Health status constants
# ---------------------------------------------------------------------------

OK = "ok"
DEGRADED = "degraded"
UNHEALTHY = "unhealthy"

_VALID_STATUSES = {OK, DEGRADED, UNHEALTHY}

# ---------------------------------------------------------------------------
# HealthResponse schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthResponse:
    """Structured health check response.

    Attributes:
        status:     ``"ok"``, ``"degraded"``, or ``"unhealthy"``.
        timestamp:  ISO-8601 timestamp of the check.
        component:  The S4 component being checked (e.g. ``"s4"``,
                    ``"worker_pool"``).
        details:    Flat key/value map of diagnostic information.
    """

    status: str
    timestamp: str
    component: str
    details: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            object.__setattr__(self, "status", UNHEALTHY)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "timestamp": self.timestamp,
            "component": self.component,
            "details": dict(self.details),
        }


# ---------------------------------------------------------------------------
# Module-level runtime references
#
# Set via register_*() or init_health() at daemon startup.  Cleared via
# clear_registrations() so tests can isolate state.
# ---------------------------------------------------------------------------

_lock = threading.Lock()

_daemon_started_at: float = 0.0
_daemon_shutdown: bool = False

# Optional callables queried by the check functions.  Using callables
# avoids coupling the health module to concrete runtime types.
_queue_depth_fn: Callable[[], int] | None = None
_supervisor_health_fn: (
    Callable[[], dict[str, int]] | None
) = None  # returns {"healthy": N, "unhealthy": N, "total": N}
_supervisor_running_fn: Callable[[], bool] | None = None
_panic_active_fn: Callable[[], bool] | None = None
_worker_pool_detail_fn: (
    Callable[[], dict[str, Any]] | None
) = None  # returns detailed worker info

# Event substrate reachability check — defaults to emitting a test metric.
_liveness_substrate_fn: Callable[[], bool] | None = None


def _default_substrate_check() -> bool:
    """Try to emit a metric to verify the event substrate is reachable."""
    try:
        from src.platform.observability.metrics import emit_metric

        emit_metric("s4.health.liveness", 1, {"check": "liveness"})
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Registration API
# ---------------------------------------------------------------------------


def init_health() -> None:
    """Initialise health check module-level state.

    Call once at daemon startup.  Resets all references to defaults.
    """
    global _daemon_started_at, _daemon_shutdown
    with _lock:
        _daemon_started_at = time.time()
        _daemon_shutdown = False
        _liveness_substrate_fn = _default_substrate_check


def mark_shutdown() -> None:
    """Mark the daemon as shutdown (liveness will return unhealthy)."""
    global _daemon_shutdown
    with _lock:
        _daemon_shutdown = True


def register_queue_depth(fn: Callable[[], int]) -> None:
    """Register a callable that returns the current queue depth."""
    global _queue_depth_fn
    with _lock:
        _queue_depth_fn = fn


def register_supervisor_health(
    fn: Callable[[], dict[str, int]],
) -> None:
    """Register a callable returning ``{"healthy": N, "unhealthy": N, "total": N}``."""
    global _supervisor_health_fn
    with _lock:
        _supervisor_health_fn = fn


def register_supervisor_running(fn: Callable[[], bool]) -> None:
    """Register a callable that returns whether supervisors are running."""
    global _supervisor_running_fn
    with _lock:
        _supervisor_running_fn = fn


def register_panic_active(fn: Callable[[], bool]) -> None:
    """Register a callable that returns whether the panic guard is active."""
    global _panic_active_fn
    with _lock:
        _panic_active_fn = fn


def register_worker_pool_detail(fn: Callable[[], dict[str, Any]]) -> None:
    """Register a callable returning detailed worker pool information."""
    global _worker_pool_detail_fn
    with _lock:
        _worker_pool_detail_fn = fn


def register_liveness_substrate(fn: Callable[[], bool]) -> None:
    """Register a custom event substrate reachability check."""
    global _liveness_substrate_fn
    with _lock:
        _liveness_substrate_fn = fn


def clear_registrations() -> None:
    """Clear all module-level state (for test isolation)."""
    global \
        _daemon_started_at, \
        _daemon_shutdown, \
        _queue_depth_fn, \
        _supervisor_health_fn, \
        _supervisor_running_fn, \
        _panic_active_fn, \
        _worker_pool_detail_fn
    with _lock:
        _daemon_started_at = 0.0
        _daemon_shutdown = False
        _queue_depth_fn = None
        _supervisor_health_fn = None
        _supervisor_running_fn = None
        _panic_active_fn = None
        _worker_pool_detail_fn = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(component: str, **details: str) -> HealthResponse:
    return HealthResponse(OK, _iso_now(), component, details)


def _degraded(component: str, **details: str) -> HealthResponse:
    return HealthResponse(DEGRADED, _iso_now(), component, details)


def _unhealthy(component: str, **details: str) -> HealthResponse:
    return HealthResponse(UNHEALTHY, _iso_now(), component, details)


# ---------------------------------------------------------------------------
# Liveness check
# ---------------------------------------------------------------------------


def check_liveness() -> HealthResponse:
    """Report whether the S4 daemon is running and responsive.

    Returns OK if:
    - ``init_health()`` has been called
    - ``mark_shutdown()`` has not been called
    - the event substrate (metrics) can be written to

    Returns UNHEALTHY otherwise.
    """
    with _lock:
        if _daemon_started_at <= 0:
            return _unhealthy("s4", daemon="not_initialised")
        if _daemon_shutdown:
            return _unhealthy("s4", daemon="shutdown")
        substrate_fn = _liveness_substrate_fn or _default_substrate_check

    if not substrate_fn():
        return _unhealthy("s4", daemon="alive", event_substrate="unreachable")

    return _ok("s4", daemon="running")


# ---------------------------------------------------------------------------
# Readiness check
# ---------------------------------------------------------------------------

_QUEUE_WARN_THRESHOLD = 50


def check_readiness() -> HealthResponse:
    """Report whether S4 can accept and process new jobs.

    Returns OK if:
    - liveness passes
    - queue depth is below warning threshold
    - at least one healthy worker exists (if supervisor is configured)
    - supervisors are running (if configured)
    - panic guard is not active

    Returns DEGRADED if queue depth is high or worker pool is partially
    unhealthy.

    Returns UNHEALTHY if no workers are healthy or panic guard is active.
    """
    # Start with liveness — if the daemon isn't alive, we're not ready.
    liveness = check_liveness()
    if liveness.status != OK:
        return _unhealthy(
            "s4",
            reason="daemon_not_alive",
            liveness_status=liveness.status,
        )

    details: dict[str, str] = {}

    with _lock:
        qfn = _queue_depth_fn
        sfn = _supervisor_health_fn
        rfn = _supervisor_running_fn
        pfn = _panic_active_fn

    # Queue depth
    depth = None
    if qfn is not None:
        try:
            depth = qfn()
            details["queue_depth"] = str(depth)
        except Exception:
            details["queue_depth"] = "error"

    # Supervisor health
    supervisor_healthy: int | None = None
    supervisor_unhealthy: int | None = None
    supervisor_total: int | None = None
    if sfn is not None:
        try:
            info = sfn()
            supervisor_healthy = info.get("healthy", 0)
            supervisor_unhealthy = info.get("unhealthy", 0)
            supervisor_total = info.get("total", 0)
            details["healthy_workers"] = str(supervisor_healthy)
            details["unhealthy_workers"] = str(supervisor_unhealthy)
            details["total_workers"] = str(supervisor_total)
        except Exception:
            details["healthy_workers"] = "error"

    # Supervisor running
    supervisors_running = True
    if rfn is not None:
        try:
            supervisors_running = rfn()
            details["supervisors_running"] = str(supervisors_running).lower()
        except Exception:
            details["supervisors_running"] = "error"

    # Panic guard
    panic_active = False
    if pfn is not None:
        try:
            panic_active = pfn()
            details["panic_guard_active"] = str(panic_active).lower()
        except Exception:
            details["panic_guard_active"] = "error"

    # --- Decision logic ---

    # Unhealthy conditions
    if panic_active:
        return _unhealthy("s4", **details, reason="panic_guard_active")

    if supervisor_total is not None and supervisor_healthy == 0:
        return _unhealthy("s4", **details, reason="no_healthy_workers")

    # Degraded conditions
    degraded_reasons: list[str] = []
    if depth is not None and depth >= _QUEUE_WARN_THRESHOLD:
        degraded_reasons.append(f"queue_depth_{depth}")

    if supervisor_unhealthy is not None and supervisor_unhealthy > 0:
        degraded_reasons.append(f"{supervisor_unhealthy}_unhealthy_workers")

    if not supervisors_running:
        degraded_reasons.append("supervisor_not_running")

    if degraded_reasons:
        return _degraded("s4", **details, reason=";".join(degraded_reasons))

    return _ok("s4", **details, reason="ready")


# ---------------------------------------------------------------------------
# Worker Pool Health check
# ---------------------------------------------------------------------------


def check_worker_pool_health() -> HealthResponse:
    """Report detailed worker pool health.

    Returns cached heartbeat / restart data without blocking on worker
    responses.

    Returns an unhealthy response with a clear message if the worker pool
    detail provider has not been registered.
    """
    with _lock:
        fn = _worker_pool_detail_fn

    if fn is None:
        return _unhealthy(
            "worker_pool",
            reason="no_worker_pool_registered",
        )

    try:
        info = fn()
    except Exception as exc:
        return _unhealthy(
            "worker_pool",
            reason="detail_provider_error",
            error=str(exc),
        )

    total = info.get("total_workers", 0)
    healthy = info.get("healthy_workers", 0)
    unhealthy = info.get("unhealthy_workers", 0)

    detail: dict[str, str] = {
        "total_workers": str(total),
        "healthy_workers": str(healthy),
        "unhealthy_workers": str(unhealthy),
    }

    # Include optional heartbeat/restart data
    heartbeats = info.get("worker_heartbeats")
    if heartbeats is not None:
        detail["worker_heartbeats"] = str(heartbeats)

    restart_counts = info.get("worker_restart_counts")
    if restart_counts is not None:
        detail["worker_restart_counts"] = str(restart_counts)

    if unhealthy > 0 and healthy == 0:
        return _unhealthy("worker_pool", **detail, reason="all_workers_unhealthy")
    if unhealthy > 0:
        return _degraded("worker_pool", **detail, reason="some_workers_unhealthy")
    if total == 0:
        return _degraded("worker_pool", **detail, reason="no_workers")

    return _ok("worker_pool", **detail, reason="healthy")
