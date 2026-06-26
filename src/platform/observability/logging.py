"""Logging v1 — Stratum-4 structured log emission.

Provides a single public function ``log()`` that S4 components use to emit
structured log events with correlation IDs and trace IDs.  Logs are **never
formatted as text, rotated, or shipped** by this module — they are only
emitted to a configured sink.

Design constraints (from S4.8.2):

- Must never block worker loops, supervisor loops, or the daemon.
- Must never raise exceptions.
- Must be safe to call from any thread.
- Must be transport-agnostic (swap sinks, not code).
- Every log entry must include ``correlation_id``, ``trace_id``, and a
  flat ``fields`` map.

Usage::

    from src.platform.observability.logging import log

    log("info", "job_state_transition", {
        "job_id": "abc-123", "from": "pending", "to": "running",
    })

IDs are automatically injected from the current ``LogContext``::

    from src.platform.observability.logging import LogContext, log

    with LogContext(correlation_id="job-abc-123", trace_id="trace-x"):
        log("info", "worker_heartbeat", {"worker_id": "w1"})
"""

from __future__ import annotations

import json
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


# ══════════════════════════════════════════════════════════════════════════════
# Log event types
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class LogEvent:
    """A single structured log event.

    Attributes:
        level:          Severity (``debug`` | ``info`` | ``warning`` |
                        ``error`` | ``critical``).
        message:        Short, stable string (e.g. ``"job_state_transition"``).
        timestamp:      ISO-8601 UTC timestamp string.
        correlation_id: Job-level or request-level context ID.
        trace_id:       Single execution path ID within a job.
        component:      S4 component that emitted the log (e.g. ``"control_plane"``).
        fields:         Flat key/value map.  Values are coerced to ``str`` so
                        sinks never receive non-string values.
    """

    level: str
    message: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    correlation_id: str = ""
    trace_id: str = ""
    component: str = ""
    fields: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the event as the canonical JSON-compatible dict."""
        return {
            "event": "log",
            "level": self.level,
            "message": self.message,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "component": self.component,
            "fields": dict(self.fields),
        }

    def to_json(self) -> str:
        """Return the event as a single JSON line (no trailing newline)."""
        return json.dumps(self.to_dict(), sort_keys=True, default=str)


# ══════════════════════════════════════════════════════════════════════════════
# Sink protocol & built-in sinks
# ══════════════════════════════════════════════════════════════════════════════


class LogSink(Protocol):
    """Protocol for log event sinks.

    A sink **must** be safe to call from any thread and **must not** raise.
    """

    def accept(self, event: LogEvent) -> None:
        """Accept and dispatch a single log event."""
        ...


class StdoutLogSink:
    """Default sink: write each log as a JSON line to stdout.

    Non-blocking (``sys.stdout.write`` is fast), requires no setup, and is
    compatible with log-aggregator pipelines that consume newline-delimited
    JSON.
    """

    def accept(self, event: LogEvent) -> None:
        """Write ``event`` as a JSON line to stderr."""
        try:
            line = event.to_json()
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
        except Exception:
            pass  # never raise


class CollectingLogSink:
    """In-memory sink that accumulates events for test/assertion purposes.

    Thread-safe via a lock.  Exposes ``events()`` and ``clear()``.

    Usage::

        sink = CollectingLogSink()
        with log_sinks(sink):
            log("info", "test", {})
        assert len(sink.events()) == 1
    """

    def __init__(self) -> None:
        self._events: deque[LogEvent] = deque()
        self._lock = threading.Lock()

    def accept(self, event: LogEvent) -> None:
        """Append ``event`` to the internal buffer."""
        with self._lock:
            self._events.append(event)

    def events(self) -> list[LogEvent]:
        """Return a snapshot of all accumulated events."""
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        """Discard all accumulated events."""
        with self._lock:
            self._events.clear()


# ══════════════════════════════════════════════════════════════════════════════
# Log context (correlation_id / trace_id propagation)
# ══════════════════════════════════════════════════════════════════════════════

_thread_local = threading.local()
"""Thread-local storage for the active ``LogContext``."""


class LogContext:
    """Context manager that sets ``correlation_id`` and ``trace_id`` for the
    current thread.

    All ``log()`` calls within the ``with`` block automatically inherit these
    IDs.  Contexts can be nested — the outer values are restored on exit.

    Usage::

        with LogContext(correlation_id="job-abc", trace_id="trace-1"):
            log("info", "worker_heartbeat", {"worker_id": "w1"})
            # correlation_id="job-abc", trace_id="trace-1"

        # Outside the block: IDs are empty (or restored to previous values)
    """

    def __init__(
        self,
        correlation_id: str = "",
        trace_id: str = "",
    ) -> None:
        self._correlation_id = correlation_id
        self._trace_id = trace_id
        self._previous: tuple[str, str] | None = None

    def __enter__(self) -> LogContext:
        self._previous = (
            getattr(_thread_local, "correlation_id", ""),
            getattr(_thread_local, "trace_id", ""),
        )
        _thread_local.correlation_id = self._correlation_id
        _thread_local.trace_id = self._trace_id
        return self

    def __exit__(self, *args: object) -> None:
        if self._previous is not None:
            _thread_local.correlation_id = self._previous[0]
            _thread_local.trace_id = self._previous[1]


def current_correlation_id() -> str:
    """Return the ``correlation_id`` active in the current thread."""
    return getattr(_thread_local, "correlation_id", "")


def current_trace_id() -> str:
    """Return the ``trace_id`` active in the current thread."""
    return getattr(_thread_local, "trace_id", "")


# ══════════════════════════════════════════════════════════════════════════════
# Global sink registry (swappable for tests / file / OTEL)
# ══════════════════════════════════════════════════════════════════════════════

_global_log_sinks: list[LogSink] = []
"""Registered log sinks.  Populated at import time with the default sink."""

_lock = threading.Lock()
"""Protects ``_global_log_sinks`` against concurrent modification."""

_verbose = False
"""If ``False``, ``log()`` is a no-op.  Set via ``set_verbose()``."""


def set_verbose(enable: bool = True) -> None:
    """Enable or disable log emission globally.

    Args:
        enable: ``True`` to emit logs (default), ``False`` to silence.
    """
    global _verbose
    _verbose = enable


def register_log_sink(sink: LogSink) -> None:
    """Register a log sink.

    Sinks are called **synchronously** from ``log()``.  Each sink **must** be
    safe to call from any thread and **must not** raise.

    Args:
        sink: A ``LogSink`` instance.
    """
    with _lock:
        _global_log_sinks.append(sink)


def clear_log_sinks() -> None:
    """Remove all registered sinks (used in tests)."""
    with _lock:
        _global_log_sinks.clear()


# Register the default stdout sink at import time
register_log_sink(StdoutLogSink())


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════


def log(
    level: str,
    message: str,
    fields: dict[str, Any] | None = None,
    component: str = "",
    *,
    _timestamp: str | None = None,
    _correlation_id: str | None = None,
    _trace_id: str | None = None,
) -> None:
    """Emit a structured log event.

    Args:
        level:     Severity (``debug`` | ``info`` | ``warning`` | ``error`` |
                   ``critical``).
        message:   Short, stable string identifier
                   (e.g. ``"job_state_transition"``).
        fields:    Flat key/value map.  Values are coerced to ``str`` so sinks
                   never receive non-string values.
        component: Optional S4 component name (e.g. ``"control_plane"``).
                   Provided as a keyword when the caller is not the component
                   itself but has the information.

    Rules:
        - Never blocks.
        - Never raises.
        - Safe to call from any S4 component.
        - ``correlation_id`` and ``trace_id`` are automatically injected from
          the current ``LogContext`` if not overridden via ``_correlation_id`` /
          ``_trace_id``.
    """
    if not _verbose:
        return

    try:
        safe_fields: dict[str, str] = {}
        if fields:
            for k, v in fields.items():
                try:
                    safe_fields[str(k)] = str(v)
                except Exception:
                    safe_fields[str(k)] = "<error>"

        cid = _correlation_id if _correlation_id is not None else current_correlation_id()
        tid = _trace_id if _trace_id is not None else current_trace_id()

        event = LogEvent(
            level=level,
            message=message,
            timestamp=_timestamp or datetime.now(timezone.utc).isoformat(),
            correlation_id=cid,
            trace_id=tid,
            component=component,
            fields=safe_fields,
        )

        with _lock:
            sinks = list(_global_log_sinks)

        for sink in sinks:
            try:
                sink.accept(event)
            except Exception:
                pass  # sink failure must never propagate

    except Exception:
        pass  # top-level guard — log() must never raise


# ══════════════════════════════════════════════════════════════════════════════
# Category helpers
# ══════════════════════════════════════════════════════════════════════════════


def log_job_state_transition(
    job_id: str,
    from_state: str,
    to_state: str,
    component: str = "",
) -> None:
    """Emit a log entry for a job state transition.

    Args:
        job_id:     The job's unique identifier.
        from_state: Previous state.
        to_state:   New state.
        component:  Component that performed the transition
                    (e.g. ``"control_plane"``).
    """
    log(
        "info",
        "job_state_transition",
        {"job_id": job_id, "from": from_state, "to": to_state},
        component=component,
    )


def log_worker_activity(
    worker_id: str,
    status: str,
    job_id: str = "",
    component: str = "",
) -> None:
    """Emit a log entry for worker activity (heartbeat, status change, etc.).

    Args:
        worker_id:  The worker's unique identifier.
        status:     Current status (e.g. ``"healthy"``, ``"unhealthy"``).
        job_id:     Optional job ID the worker is processing.
        component:  Component that generated the log.
    """
    fields: dict[str, Any] = {"worker_id": worker_id, "status": status}
    if job_id:
        fields["job_id"] = job_id
    log("info", "worker_activity", fields, component=component)


def log_queue_event(
    queue_name: str,
    action: str,
    depth: int,
    job_id: str = "",
    component: str = "",
) -> None:
    """Emit a log entry for a queue operation.

    Args:
        queue_name: Queue name (e.g. ``"default"``).
        action:     Operation (e.g. ``"enqueue"``, ``"dequeue"``).
        depth:      Queue depth after the operation.
        job_id:     Optional job ID involved in the operation.
        component:  Component that generated the log.
    """
    fields: dict[str, Any] = {
        "queue": queue_name,
        "action": action,
        "depth": str(depth),
    }
    if job_id:
        fields["job_id"] = job_id
    log("info", "queue_event", fields, component=component)


def log_execution(
    worker_id: str,
    job_type: str,
    duration_ms: float,
    component: str = "",
) -> None:
    """Emit a log entry for a job execution.

    Args:
        worker_id:   The worker that executed the job.
        job_type:    Job type (e.g. channel name).
        duration_ms: Execution duration in milliseconds.
        component:   Component that generated the log.
    """
    log(
        "info",
        "execution",
        {
            "worker_id": worker_id,
            "job_type": job_type,
            "duration_ms": str(int(duration_ms)),
        },
        component=component,
    )


def log_supervisor_action(
    action: str,
    reason: str,
    worker_id: str = "",
    job_id: str = "",
    component: str = "supervisor_loop",
) -> None:
    """Emit a log entry for a supervisor action.

    Args:
        action:    Action type (e.g. ``"repair"``, ``"poison"``, ``"panic"``,
                   ``"retry"``).
        reason:    Human-readable reason for the action.
        worker_id: Optional worker ID involved.
        job_id:    Optional job ID involved.
        component: Component that generated the log.
    """
    fields: dict[str, Any] = {"action": action, "reason": reason}
    if worker_id:
        fields["worker_id"] = worker_id
    if job_id:
        fields["job_id"] = job_id
    log("warning", "supervisor_action", fields, component=component)


# ══════════════════════════════════════════════════════════════════════════════
# Backward-compatible wrappers (preserve existing call sites)
# ══════════════════════════════════════════════════════════════════════════════


def log_job_created(job: Any) -> None:
    """Emit when a job is created and enqueued.  (Legacy API.)

    Args:
        job: A ``Job`` instance (must have ``job_id`` and ``payload``).
    """
    job_type = getattr(job.payload, "channel", "unknown")
    log(
        "info",
        "job_created",
        {"job_id": job.job_id, "job_type": job_type},
        component="runtime",
        _correlation_id=job.job_id,
    )


def log_job_started(job: Any) -> None:
    """Emit when a worker picks up a job for execution.  (Legacy API.)

    Args:
        job: A ``Job`` instance (must have ``job_id`` and ``payload``).
    """
    job_type = getattr(job.payload, "channel", "unknown")
    log(
        "info",
        "job_started",
        {"job_id": job.job_id, "job_type": job_type},
        component="worker",
        _correlation_id=job.job_id,
    )


def log_job_finished(job: Any) -> None:
    """Emit when a worker finishes executing a job.  (Legacy API.)

    Args:
        job: A ``Job`` instance (must have ``job_id`` and ``payload``).
    """
    job_type = getattr(job.payload, "channel", "unknown")
    log(
        "info",
        "job_finished",
        {"job_id": job.job_id, "job_type": job_type},
        component="worker",
        _correlation_id=job.job_id,
    )
