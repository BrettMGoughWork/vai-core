"""
Dashboard Event Model — in-memory state derived from S4 observability events.

Maintains a live, aggregated view of:
- Job list (state transitions, ages, worker assignments)
- Worker list (heartbeats, health, active jobs)
- Trace hierarchy (job → cycle → segment trees)
- Metric aggregations (counts, histograms, rates)
- Health check snapshots

All state is derived from JSON-line events emitted by S4 components.
The dashboard never mutates S4 state.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ══════════════════════════════════════════════════════════════════════════════
# Data types
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class JobInfo:
    """In-memory representation of a single S4 job."""

    job_id: str
    job_type: str = ""
    state: str = "pending"
    channel: str = ""
    retries: int = 0
    worker_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    duration_ms: float = 0.0


@dataclass
class WorkerInfo:
    """In-memory representation of a single S4 worker."""

    worker_id: str
    status: str = "unknown"
    healthy: bool = True
    last_heartbeat: str = ""
    restart_count: int = 0
    active_job_id: str = ""
    job_type: str = ""


@dataclass
class TraceNode:
    """A single node in the trace hierarchy."""

    trace_id: str
    trace_type: str  # "job" | "cycle" | "segment"
    parent_trace_id: str = ""
    correlation_id: str = ""
    timestamp: str = ""
    component: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    children: list[TraceNode] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class MetricSnapshot:
    """Aggregated metric values."""

    job_count: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    queue_depth: float = 0.0
    worker_health: dict[str, float] = field(default_factory=dict)
    execution_times: list[float] = field(default_factory=list)
    drift_frequency: float = 0.0
    last_updated: str = ""


@dataclass
class HealthSnapshot:
    """Latest health check result."""

    status: str = "unknown"  # ok | degraded | unhealthy
    component: str = ""
    details: dict[str, str] = field(default_factory=dict)
    timestamp: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# Event store
# ══════════════════════════════════════════════════════════════════════════════


class DashboardEventStore:
    """In-memory store of S4 observability state.

    Thread-safe.  Ingests JSON-line events from any source (stdin, file, pipe)
    and updates internal data structures.  Exposes snapshot methods for the
    dashboard UI.
    """

    def __init__(self, max_events: int = 5000) -> None:
        self._max_events = max_events
        self._lock = threading.Lock()

        # Raw event ring buffer (for SSE streaming)
        self._recent_events: deque[dict[str, Any]] = deque(maxlen=max_events)

        # Derived state
        self._jobs: dict[str, JobInfo] = {}
        self._workers: dict[str, WorkerInfo] = {}
        self._traces: dict[str, TraceNode] = {}
        self._trace_roots: list[str] = []  # ordered list of root trace IDs
        self._metrics = MetricSnapshot()
        self._health: HealthSnapshot = HealthSnapshot()

        # SSE subscribers
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        self._sub_lock = threading.Lock()

        # Running counters
        self._drift_count: int = 0
        self._total_jobs_completed: int = 0

    # ── Subscriber management (for SSE) ──────────────────────────────────

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register an SSE subscriber callback."""
        with self._sub_lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Remove an SSE subscriber callback."""
        with self._sub_lock:
            self._subscribers.remove(callback)

    def _notify(self, event: dict[str, Any]) -> None:
        """Push an event to all SSE subscribers."""
        with self._sub_lock:
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(event)
            except Exception:
                pass  # subscriber failure must never propagate

    # ── Ingestion ────────────────────────────────────────────────────────

    def ingest_json_line(self, line: str) -> None:
        """Parse a JSON line and update internal state.

        Args:
            line: A single JSON line (without trailing newline).
        """
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return

        if not isinstance(data, dict):
            return

        # Store raw event
        with self._lock:
            self._recent_events.append(data)

        # Route by event type
        event_type = data.get("event", "")
        if event_type == "metric":
            self._ingest_metric(data)
        elif event_type == "trace":
            self._ingest_trace(data)
        elif event_type == "log":
            self._ingest_log(data)
        elif event_type in ("health", "health_check"):
            self._ingest_health(data)

        # Notify SSE subscribers (after state update)
        self._notify(data)

    def _ingest_metric(self, data: dict[str, Any]) -> None:
        """Update metric aggregations from a metric event."""
        name = data.get("metric", "")
        value = data.get("value", 0.0)
        labels = data.get("labels", {})

        with self._lock:
            if name == "s4.job.count":
                state = labels.get("state", "unknown")
                self._metrics.job_count[state] = value
                if state == "completed" or state == "succeeded":
                    self._total_jobs_completed += 1
            elif name == "s4.queue.depth":
                self._metrics.queue_depth = value
            elif name == "s4.worker.health":
                wid = labels.get("worker_id", "unknown")
                self._metrics.worker_health[wid] = value
                self._update_worker_from_metric(wid, value, labels)
            elif name == "s4.job.executiontimems":
                self._metrics.execution_times.append(float(value))
                # Keep last 100 execution times
                if len(self._metrics.execution_times) > 100:
                    self._metrics.execution_times = self._metrics.execution_times[-100:]
                # Update job duration
                job_id = labels.get("job_id", "")
                if job_id and job_id in self._jobs:
                    self._jobs[job_id].duration_ms = float(value)
            elif "drift" in name.lower() or "repair" in name.lower():
                self._drift_count += 1
                # Calculate drift frequency per 100 jobs
                if self._total_jobs_completed > 0:
                    self._metrics.drift_frequency = (
                        self._drift_count / self._total_jobs_completed
                    )

            self._metrics.last_updated = datetime.now(timezone.utc).isoformat()

    def _update_worker_from_metric(
        self, worker_id: str, health_value: float, labels: dict[str, str]
    ) -> None:
        """Create or update a worker record from a health metric."""
        if worker_id not in self._workers:
            self._workers[worker_id] = WorkerInfo(worker_id=worker_id)

        worker = self._workers[worker_id]
        worker.healthy = health_value >= 1.0
        worker.status = "healthy" if worker.healthy else "unhealthy"
        worker.last_heartbeat = datetime.now(timezone.utc).isoformat()

        # Extract restart count if present
        restart_str = labels.get("restart_count", "")
        if restart_str:
            try:
                worker.restart_count = int(restart_str)
            except (ValueError, TypeError):
                pass

    def _ingest_trace(self, data: dict[str, Any]) -> None:
        """Update trace tree from a trace event."""
        trace_type = data.get("trace_type", "")
        trace_id = data.get("trace_id", "")
        parent_id = data.get("parent_trace_id", "")
        correlation_id = data.get("correlation_id", "")
        timestamp = data.get("timestamp", "")
        component = data.get("component", "")
        fields = data.get("fields", {})

        if not trace_id:
            return

        node = TraceNode(
            trace_id=trace_id,
            trace_type=trace_type,
            parent_trace_id=parent_id,
            correlation_id=correlation_id,
            timestamp=timestamp,
            component=component,
            fields=dict(fields),
        )

        with self._lock:
            # Extract duration if present
            duration_str = fields.get("duration_ms", "")
            if duration_str:
                try:
                    node.duration_ms = float(duration_str)
                except (ValueError, TypeError):
                    pass

            self._traces[trace_id] = node

            # Link to parent
            if parent_id and parent_id in self._traces:
                parent = self._traces[parent_id]
                # Avoid duplicate children
                if not any(c.trace_id == trace_id for c in parent.children):
                    parent.children.append(node)

            # Track root traces
            if trace_type == "job" and not parent_id:
                if trace_id not in self._trace_roots:
                    self._trace_roots.append(trace_id)
                    # Keep last 50 root traces
                    if len(self._trace_roots) > 50:
                        self._trace_roots = self._trace_roots[-50:]

            # Update job state from trace fields
            job_id = fields.get("job_id", "")
            if job_id:
                if job_id not in self._jobs:
                    self._jobs[job_id] = JobInfo(job_id=job_id)
                    self._jobs[job_id].created_at = timestamp

                job = self._jobs[job_id]
                job.updated_at = timestamp

                if trace_type == "job":
                    from_state = fields.get("from", "")
                    to_state = fields.get("to", "")
                    if to_state:
                        job.state = to_state
                    if component:
                        pass  # don't overwrite component

                elif trace_type == "cycle":
                    action = fields.get("action", "")
                    if action == "start":
                        worker_id = fields.get("worker_id", "")
                        if worker_id:
                            job.worker_id = worker_id
                            self._update_worker_job(worker_id, job_id)
                            try:
                                job.retries = int(fields.get("attempt", "0"))
                            except (ValueError, TypeError):
                                pass

    def _update_worker_job(self, worker_id: str, job_id: str) -> None:
        """Associate a worker with a job."""
        if worker_id not in self._workers:
            self._workers[worker_id] = WorkerInfo(worker_id=worker_id)
        self._workers[worker_id].active_job_id = job_id

    def _ingest_log(self, data: dict[str, Any]) -> None:
        """Update state from structured log events."""
        message = data.get("message", "")
        fields = data.get("fields", {})

        if "job_created" in message:
            job_id = fields.get("job_id", "")
            job_type = fields.get("job_type", "")
            if job_id and job_id not in self._jobs:
                self._jobs[job_id] = JobInfo(
                    job_id=job_id,
                    job_type=job_type,
                    state="pending",
                    created_at=data.get("timestamp", ""),
                )

        elif "job_started" in message:
            job_id = fields.get("job_id", "")
            if job_id and job_id in self._jobs:
                self._jobs[job_id].state = "running"

        elif "job_finished" in message:
            job_id = fields.get("job_id", "")
            if job_id and job_id in self._jobs:
                self._jobs[job_id].state = "completed"

        elif "execution" in message:
            duration_str = fields.get("duration_ms", "")
            job_type = fields.get("job_type", "")
            worker_id = fields.get("worker_id", "")
            if worker_id and worker_id in self._workers:
                self._workers[worker_id].job_type = job_type
                self._workers[worker_id].active_job_id = ""

        elif "queue_event" in message:
            action = fields.get("action", "")
            depth_str = fields.get("depth", "0")
            try:
                depth = float(depth_str)
            except (ValueError, TypeError):
                depth = 0.0
            self._metrics.queue_depth = depth

    def _ingest_health(self, data: dict[str, Any]) -> None:
        """Update health snapshot from a health check event."""
        with self._lock:
            self._health = HealthSnapshot(
                status=data.get("status", "ok"),
                component=data.get("component", "s4"),
                details={k: str(v) for k, v in data.get("details", {}).items()},
                timestamp=data.get("timestamp", ""),
            )

    # ── Snapshot accessors ───────────────────────────────────────────────

    def get_jobs(self) -> list[JobInfo]:
        """Return a snapshot of all tracked jobs."""
        with self._lock:
            return list(self._jobs.values())

    def get_workers(self) -> list[WorkerInfo]:
        """Return a snapshot of all tracked workers."""
        with self._lock:
            return list(self._workers.values())

    def get_trace_roots(self) -> list[TraceNode]:
        """Return a snapshot of root trace nodes (job-level traces)."""
        with self._lock:
            result = []
            for tid in self._trace_roots:
                node = self._traces.get(tid)
                if node:
                    result.append(node)
            return result

    def get_trace_tree(self, trace_id: str) -> TraceNode | None:
        """Return a full trace subtree by root trace ID."""
        with self._lock:
            node = self._traces.get(trace_id)
            if node:
                return node
            return None

    def get_metrics(self) -> MetricSnapshot:
        """Return a snapshot of aggregated metrics."""
        with self._lock:
            return self._metrics

    def get_health(self) -> HealthSnapshot:
        """Return the latest health snapshot."""
        with self._lock:
            return self._health

    def get_recent_events(self, count: int = 100) -> list[dict[str, Any]]:
        """Return the most recent raw events."""
        with self._lock:
            events = list(self._recent_events)
            return events[-count:]

    def get_summary(self) -> dict[str, Any]:
        """Return a full dashboard summary as a JSON-compatible dict."""
        jobs = self.get_jobs()
        workers = self.get_workers()
        metrics = self.get_metrics()
        health = self.get_health()

        # Count jobs by state
        state_counts: dict[str, int] = {}
        for j in jobs:
            state_counts[j.state] = state_counts.get(j.state, 0) + 1

        # Worker stats
        healthy_workers = sum(1 for w in workers if w.healthy)
        total_workers = len(workers)

        # Execution time histogram (simple buckets)
        exec_times = metrics.execution_times
        hist: dict[str, int] = {"<10ms": 0, "<50ms": 0, "<200ms": 0, "<1s": 0, ">=1s": 0}
        for t in exec_times:
            if t < 10:
                hist["<10ms"] += 1
            elif t < 50:
                hist["<50ms"] += 1
            elif t < 200:
                hist["<200ms"] += 1
            elif t < 1000:
                hist["<1s"] += 1
            else:
                hist[">=1s"] += 1

        return {
            "type": "dashboard_summary",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "jobs": {
                "total": len(jobs),
                "by_state": state_counts,
            },
            "workers": {
                "total": total_workers,
                "healthy": healthy_workers,
                "unhealthy": total_workers - healthy_workers,
            },
            "traces": {
                "total_roots": len(self._trace_roots),
                "total_nodes": len(self._traces),
            },
            "metrics": {
                "queue_depth": metrics.queue_depth,
                "drift_frequency": round(metrics.drift_frequency, 3),
                "execution_time_histogram": hist,
                "avg_execution_ms": round(sum(exec_times) / len(exec_times), 1) if exec_times else 0.0,
            },
            "health": {
                "status": health.status,
            },
        }

    def get_state_dict(self) -> dict[str, Any]:
        """Return the full dashboard state as a JSON-compatible dict.

        This is the primary snapshot used by the REST endpoint.
        """
        jobs = self.get_jobs()
        workers = self.get_workers()
        traces = self.get_trace_roots()
        metrics = self.get_metrics()
        health = self.get_health()

        def _serialize_trace(node: TraceNode) -> dict[str, Any]:
            return {
                "trace_id": node.trace_id,
                "trace_type": node.trace_type,
                "parent_trace_id": node.parent_trace_id,
                "correlation_id": node.correlation_id,
                "timestamp": node.timestamp,
                "component": node.component,
                "fields": node.fields,
                "duration_ms": node.duration_ms,
                "children": [_serialize_trace(c) for c in node.children],
            }

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "jobs": [
                {
                    "job_id": j.job_id,
                    "job_type": j.job_type,
                    "state": j.state,
                    "channel": j.channel,
                    "retries": j.retries,
                    "worker_id": j.worker_id,
                    "created_at": j.created_at,
                    "updated_at": j.updated_at,
                    "duration_ms": j.duration_ms,
                }
                for j in sorted(jobs, key=lambda x: x.updated_at, reverse=True)[:200]
            ],
            "workers": [
                {
                    "worker_id": w.worker_id,
                    "status": w.status,
                    "healthy": w.healthy,
                    "last_heartbeat": w.last_heartbeat,
                    "restart_count": w.restart_count,
                    "active_job_id": w.active_job_id,
                    "job_type": w.job_type,
                }
                for w in workers
            ],
            "traces": [_serialize_trace(t) for t in traces],
            "metrics": {
                "job_count": dict(metrics.job_count),
                "queue_depth": metrics.queue_depth,
                "worker_health": dict(metrics.worker_health),
                "execution_times": metrics.execution_times[-50:],
                "drift_frequency": round(metrics.drift_frequency, 3),
                "total_jobs_completed": self._total_jobs_completed,
                "last_updated": metrics.last_updated,
            },
            "health": {
                "status": health.status,
                "component": health.component,
                "details": health.details,
                "timestamp": health.timestamp,
            },
        }
