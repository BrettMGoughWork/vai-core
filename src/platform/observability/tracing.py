"""Tracing v1 — Stratum-4 structured trace emission.

Provides a single public function ``emit_trace()`` that S4 components use to
emit hierarchical trace events (job → cycle → segment).  Traces are **never
aggregated, stored, or visualised** by this module — they are only emitted to
a configured sink.

Design constraints (from S4.8.3):

- Must never block worker loops, supervisor loops, or the daemon.
- Must never raise exceptions.
- Must be safe to call from any thread.
- Must be transport-agnostic (swap sinks, not code).
- ``trace_id`` is unique per trace event.
- ``parent_trace_id`` links hierarchical traces.
- ``correlation_id`` ties traces to a job.

Usage::

    from src.platform.observability.tracing import emit_trace

    emit_trace("job", {"job_id": "abc-123", "from": "pending", "to": "queued"})
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


# ══════════════════════════════════════════════════════════════════════════════
# Trace event types
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TraceEvent:
    """A single structured trace event.

    Attributes:
        trace_type:     ``"job"`` | ``"cycle"`` | ``"segment"``.
        trace_id:       Unique UUID for this trace event.
        parent_trace_id: UUID of the parent trace, or ``""`` for root traces.
        correlation_id: Job-level or request-level context ID.
        timestamp:      ISO-8601 UTC timestamp string.
        component:      S4 component that emitted the trace.
        fields:         Flat key/value map.  Values are coerced to ``str`` so
                        sinks never receive non-string values.
    """

    trace_type: str
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_trace_id: str = ""
    correlation_id: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    component: str = ""
    fields: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the event as the canonical JSON-compatible dict."""
        return {
            "event": "trace",
            "trace_type": self.trace_type,
            "trace_id": self.trace_id,
            "parent_trace_id": self.parent_trace_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "component": self.component,
            "fields": dict(self.fields),
        }

    def to_json(self) -> str:
        """Return the event as a single JSON line (no trailing newline)."""
        return json.dumps(self.to_dict(), sort_keys=True, default=str)


# ══════════════════════════════════════════════════════════════════════════════
# Sink protocol & built-in sinks
# ══════════════════════════════════════════════════════════════════════════════


class TraceSink(Protocol):
    """Protocol for trace event sinks.

    A sink **must** be safe to call from any thread and **must not** raise.
    """

    def accept(self, event: TraceEvent) -> None:
        """Accept and dispatch a single trace event."""
        ...


class StdoutTraceSink:
    """Default sink: write each trace as a JSON line to stdout.

    Non-blocking (``sys.stdout.write`` is fast), requires no setup, and is
    compatible with log-aggregator pipelines that consume newline-delimited
    JSON.
    """

    def accept(self, event: TraceEvent) -> None:
        """Write ``event`` as a JSON line to stdout."""
        try:
            line = event.to_json()
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except Exception:
            pass  # never raise


class CollectingTraceSink:
    """In-memory sink that accumulates trace events for test/assertion purposes.

    Thread-safe via a lock.  Exposes ``events()`` and ``clear()``.

    Usage::

        sink = CollectingTraceSink()
        with tracing_module.sink(sink):
            emit_trace("job", {"job_id": "abc"})
        assert len(sink.events()) == 1
    """

    def __init__(self) -> None:
        self._events: deque[TraceEvent] = deque()
        self._lock = threading.Lock()

    def accept(self, event: TraceEvent) -> None:
        """Append ``event`` to the internal buffer."""
        with self._lock:
            self._events.append(event)

    def events(self) -> list[TraceEvent]:
        """Return a snapshot of all accumulated events."""
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        """Discard all accumulated events."""
        with self._lock:
            self._events.clear()


# ══════════════════════════════════════════════════════════════════════════════
# Global sink registry (swappable for tests / file / OTEL)
# ══════════════════════════════════════════════════════════════════════════════

_global_trace_sinks: list[TraceSink] = []
"""Registered trace sinks.  Populated at import time with the default sink."""

_lock = threading.Lock()
"""Protects ``_global_trace_sinks`` against concurrent modification."""


def register_trace_sink(sink: TraceSink) -> None:
    """Register a trace sink.

    Sinks are called **synchronously** from ``emit_trace()``.  Each sink
    **must** be safe to call from any thread and **must not** raise.

    Args:
        sink: A ``TraceSink`` instance.
    """
    with _lock:
        _global_trace_sinks.append(sink)


def clear_trace_sinks() -> None:
    """Remove all registered sinks (used in tests)."""
    with _lock:
        _global_trace_sinks.clear()


# Register the default stdout sink at import time
register_trace_sink(StdoutTraceSink())


# ══════════════════════════════════════════════════════════════════════════════
# Context helpers (auto-inject correlation_id)
# ══════════════════════════════════════════════════════════════════════════════

_thread_local = threading.local()


def current_correlation_id() -> str:
    """Return the active correlation_id for the current thread."""
    return getattr(_thread_local, "correlation_id", "")


def set_correlation_id(cid: str) -> None:
    """Set the correlation_id for the current thread."""
    _thread_local.correlation_id = cid


class TraceContext:
    """Context manager that sets trace metadata for the current thread.

    All ``emit_trace()`` calls within the ``with`` block automatically inherit
    these IDs.  Contexts can be nested — the outer values are restored on exit.

    Usage::

        with TraceContext(correlation_id="job-abc"):
            emit_trace("job", {"job_id": "abc"})
    """

    def __init__(self, correlation_id: str = "") -> None:
        self._correlation_id = correlation_id
        self._previous: str = ""

    def __enter__(self) -> TraceContext:
        self._previous = getattr(_thread_local, "correlation_id", "")
        _thread_local.correlation_id = self._correlation_id
        return self

    def __exit__(self, *args: object) -> None:
        _thread_local.correlation_id = self._previous


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════


_cache_trace_id: dict[str, str] = {}
"""Stable per-correlation_id trace IDs for job-level root traces."""


def _root_trace_id(correlation_id: str) -> str:
    """Return a stable root trace ID for the given correlation_id."""
    if correlation_id and correlation_id not in _cache_trace_id:
        _cache_trace_id[correlation_id] = str(uuid.uuid4())
    return _cache_trace_id.get(correlation_id, "")


def emit_trace(
    trace_type: str,
    fields: dict[str, Any] | None = None,
    *,
    parent_trace_id: str | None = None,
    component: str = "",
    _correlation_id: str | None = None,
) -> str:
    """Emit a structured trace event.

    Args:
        trace_type:      ``"job"`` | ``"cycle"`` | ``"segment"``.
        fields:          Flat key/value map.  Values are coerced to ``str``.
        parent_trace_id: Optional UUID of the parent trace.
        component:       Optional S4 component name.
        _correlation_id: Override the thread-local correlation_id.

    Returns:
        The generated ``trace_id`` for this event (useful as a
        ``parent_trace_id`` for child traces).

    Rules:
        - Never blocks.
        - Never raises.
        - Safe to call from any S4 component.
        - ``correlation_id`` is auto-injected from thread-local state.
        - A unique ``trace_id`` is generated for every call.
    """
    try:
        safe_fields: dict[str, str] = {}
        if fields:
            for k, v in fields.items():
                try:
                    safe_fields[str(k)] = str(v)
                except Exception:
                    safe_fields[str(k)] = "<error>"

        cid = _correlation_id if _correlation_id is not None else current_correlation_id()

        # Job traces use the stable root trace_id for this correlation_id so
        # that child traces (cycle, segment) can link to them via
        # ``_root_trace_id()``.
        # Cycle and segment traces get fresh trace_ids.
        if trace_type == "job":
            tid = _root_trace_id(cid)
        else:
            tid = str(uuid.uuid4())

        # Resolve parent_trace_id:
        # - Job traces are roots → parent is ""
        # - Cycle/segment traces link to the root job trace by default
        # - Explicit parent_trace_id overrides the default
        if parent_trace_id is not None:
            resolved_parent = parent_trace_id
        elif trace_type == "job":
            resolved_parent = ""
        else:
            resolved_parent = _root_trace_id(cid)

        event = TraceEvent(
            trace_type=trace_type,
            trace_id=tid,
            parent_trace_id=resolved_parent,
            correlation_id=cid,
            component=component,
            fields=safe_fields,
        )

        with _lock:
            sinks = list(_global_trace_sinks)

        for sink in sinks:
            try:
                sink.accept(event)
            except Exception:
                pass  # sink failure must never propagate

        return tid

    except Exception:
        return ""  # top-level guard — emit_trace() must never raise


# ══════════════════════════════════════════════════════════════════════════════
# Category helpers
# ══════════════════════════════════════════════════════════════════════════════


def emit_job_trace(
    job_id: str,
    from_state: str,
    to_state: str,
    component: str = "",
    *,
    _correlation_id: str | None = None,
) -> str:
    """Emit a job-level trace for a state transition.

    Args:
        job_id:     The job's unique identifier.
        from_state: Previous state.
        to_state:   New state.
        component:  Component that performed the transition.

    Returns:
        The generated ``trace_id`` for this event.
    """
    return emit_trace(
        "job",
        {"job_id": job_id, "from": from_state, "to": to_state},
        component=component,
        _correlation_id=_correlation_id or job_id,
    )


def emit_cycle_trace(
    job_id: str,
    worker_id: str,
    attempt: int,
    action: str,
    duration_ms: int | None = None,
    component: str = "",
    *,
    parent_trace_id: str | None = None,
    _correlation_id: str | None = None,
) -> str:
    """Emit a cycle-level trace for a worker execution attempt.

    Args:
        job_id:          The job being processed.
        worker_id:       The worker executing the cycle.
        attempt:         Attempt number (1-based).
        action:          ``"start"`` | ``"end"`` | ``"retry"`` | ``"timeout"``.
        duration_ms:     Duration in milliseconds (for ``"end"`` / ``"retry"``).
        component:       Component that performed the cycle.
        parent_trace_id: Link to the parent job trace.
        _correlation_id: Override the thread-local correlation_id.

    Returns:
        The generated ``trace_id`` for this event.
    """
    fields: dict[str, Any] = {
        "job_id": job_id,
        "worker_id": worker_id,
        "attempt": str(attempt),
        "action": action,
    }
    if duration_ms is not None:
        fields["duration_ms"] = str(duration_ms)
    return emit_trace(
        "cycle",
        fields,
        parent_trace_id=parent_trace_id,
        component=component,
        _correlation_id=_correlation_id or job_id,
    )


def emit_segment_trace(
    job_id: str,
    segment: str,
    action: str,
    component: str = "",
    *,
    parent_trace_id: str | None = None,
    _correlation_id: str | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> str:
    """Emit a segment-level trace for a logical sub-unit of execution.

    Args:
        job_id:          The job being processed.
        segment:         Segment name (e.g. ``"preflight"``, ``"execution"``).
        action:          ``"start"`` | ``"end"`` | ``"drift"`` | ``"repair"``.
        component:       Component that performed the segment.
        parent_trace_id: Link to the parent cycle trace.
        _correlation_id: Override the thread-local correlation_id.
        extra_fields:    Additional fields to include (flat key/value).

    Returns:
        The generated ``trace_id`` for this event.
    """
    fields: dict[str, Any] = {
        "job_id": job_id,
        "segment": segment,
        "action": action,
    }
    if extra_fields:
        fields.update(extra_fields)
    return emit_trace(
        "segment",
        fields,
        parent_trace_id=parent_trace_id,
        component=component,
        _correlation_id=_correlation_id or job_id,
    )
