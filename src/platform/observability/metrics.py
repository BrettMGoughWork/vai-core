"""Metrics v1 — Stratum-4 structured metric emission.

Provides a single public function ``emit_metric()`` that S4 components use to
emit structured metric events.  Metrics are **never aggregated, stored,
visualised, or interpreted** by this module — they are only emitted to a
configured sink.

Design constraints (from S4.8.1):

- Must never block worker loops, supervisor loops, or the daemon.
- Must never raise exceptions.
- Must be safe to call from any thread.
- Must be transport-agnostic (swap sinks, not code).
- Values must be numeric; labels must be flat key/string maps.

Usage::

    from src.platform.observability.metrics import emit_metric

    emit_metric("s4.job.count", 1, {"state": "queued"})
"""

from __future__ import annotations

import json
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol


# ══════════════════════════════════════════════════════════════════════════════
# Metric event types
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MetricEvent:
    """A single structured metric event.

    Attributes:
        name:      Stable string identifier (e.g. ``"s4.job.count"``).
        value:     Numeric value (int or float).
        labels:    Flat key/value string map.  Values are coerced to
                   ``str`` so sinks never receive non-string label values.
        timestamp: ISO-8601 UTC timestamp string.
    """

    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Return the event as the canonical JSON-compatible dict."""
        return {
            "event": "metric",
            "metric": self.name,
            "value": self.value,
            "timestamp": self.timestamp,
            "labels": dict(self.labels),
        }

    def to_json(self) -> str:
        """Return the event as a single JSON line (no trailing newline)."""
        return json.dumps(self.to_dict(), sort_keys=True, default=str)


# ══════════════════════════════════════════════════════════════════════════════
# Sink protocol & built-in sinks
# ══════════════════════════════════════════════════════════════════════════════


class MetricSink(Protocol):
    """Protocol for metric event sinks.

    A sink **must** be safe to call from any thread and **must not** raise.
    """

    def accept(self, event: MetricEvent) -> None:
        """Accept and dispatch a single metric event."""
        ...


class StdoutSink:
    """Default sink: write each metric as a JSON line to stdout.

    This sink is non-blocking (``sys.stdout.write`` is fast), requires no
    setup, and is compatible with log-aggregator pipelines that consume
    newline-delimited JSON.
    """

    def accept(self, event: MetricEvent) -> None:
        """Write ``event`` as a JSON line to stdout."""
        try:
            line = event.to_json()
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except Exception:
            pass  # never raise


class CollectingSink:
    """In-memory sink that accumulates events for test/assertion purposes.

    Thread-safe via a lock.  Exposes ``events()`` and ``clear()``.

    Usage::

        sink = CollectingSink()
        with metrics_module.sink(sink):
            emit_metric("s4.job.count", 1, {"state": "queued"})
        assert len(sink.events()) == 1
    """

    def __init__(self) -> None:
        self._events: deque[MetricEvent] = deque()
        self._lock = threading.Lock()

    def accept(self, event: MetricEvent) -> None:
        """Append ``event`` to the internal buffer."""
        with self._lock:
            self._events.append(event)

    def events(self) -> list[MetricEvent]:
        """Return a snapshot of all accumulated events."""
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        """Discard all accumulated events."""
        with self._lock:
            self._events.clear()


# ══════════════════════════════════════════════════════════════════════════════
# Global sink registry (swappable for tests / Prometheus / OTEL)
# ══════════════════════════════════════════════════════════════════════════════

_global_sinks: list[MetricSink] = []
"""Registered metric sinks.  Populated at import time with the default sink."""

_lock = threading.Lock()
"""Protects ``_global_sinks`` against concurrent modification."""


def register_sink(sink: MetricSink) -> None:
    """Register a metric sink.

    Sinks are called **synchronously** from ``emit_metric()``.  Each sink
    **must** be safe to call from any thread and **must not** raise.

    Args:
        sink: A ``MetricSink`` instance.
    """
    with _lock:
        _global_sinks.append(sink)


def clear_sinks() -> None:
    """Remove all registered sinks (used in tests)."""
    with _lock:
        _global_sinks.clear()


# Register the default stdout sink at import time
register_sink(StdoutSink())


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════


def emit_metric(
    name: str,
    value: float,
    labels: dict[str, Any] | None = None,
    _timestamp: str | None = None,
) -> None:
    """Emit a structured metric event.

    Args:
        name:   Stable string identifier (e.g. ``"s4.job.count"``).
        value:  Numeric value (int or float).
        labels: Flat key/value map.  Values are coerced to ``str`` so sinks
                never receive non-string label values.

    Rules:
        - Never blocks.
        - Never raises.
        - Safe to call from any S4 component.
    """
    try:
        safe_labels: dict[str, str] = {}
        if labels:
            for k, v in labels.items():
                try:
                    safe_labels[str(k)] = str(v)
                except Exception:
                    safe_labels[str(k)] = "<error>"

        event = MetricEvent(
            name=name,
            value=float(value),
            labels=safe_labels,
            timestamp=_timestamp or datetime.now(timezone.utc).isoformat(),
        )

        with _lock:
            sinks = list(_global_sinks)

        for sink in sinks:
            try:
                sink.accept(event)
            except Exception:
                pass  # sink failure must never propagate

    except Exception:
        pass  # top-level guard — emit_metric must never raise
