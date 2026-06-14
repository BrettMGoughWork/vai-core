# Observability — Structured Logging, Metrics, Tracing

**Purpose:** A deterministic, low-overhead observability model covering all S4
components. Every subsystem emits structured events that can be consumed via
stdout, Prometheus, or the live dashboard.

---

## Design Principles

- **Never block, never raise.** Observability functions are wrapped in
  `try/except Exception: pass` — they are safe from any thread.
- **Transport-agnostic.** Logs, metrics, and traces write to pluggable sinks
  (stdout, collecting sink for tests).
- **All deterministic.** Same inputs → same outputs. No sampling. No async.

---

## Structured Logging

File: `src/platform/observability/logging.py`

### LogEvent

```python
@dataclass(frozen=True)
class LogEvent:
    timestamp: float
    severity: str          # "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL"
    category: str          # "job.state" | "worker.activity" | "queue.event" | ...
    component: str         # "ControlPlane" | "WorkerPool" | "InMemoryQueue" | ...
    message: str
    correlation_id: str | None
    trace_id: str | None
```

### LogContext

Uses `threading.local()` for context propagation:

```python
ctx = LogContext()
ctx.set(correlation_id="corr-123", trace_id="trace-456")
# All log helpers in this thread automatically attach correlation_id/trace_id
ctx.clear()
```

### Category Helpers

| Helper | Category | Use |
|--------|----------|-----|
| `log_job_state_transition()` | `job.state` | Fired on every JobState change |
| `log_worker_activity()` | `worker.activity` | Worker lifecycle events |
| `log_queue_event()` | `queue.event` | Push/pop/ack/requeue/nack |
| `log_execution()` | `exec` | S2→S1→back adapter execution |
| `log_supervisor_action()` | `supervisor.action` | Supervisor decisions |

---

## Metrics Emission

File: `src/platform/observability/metrics.py`

### MetricEvent

```python
@dataclass(frozen=True)
class MetricEvent:
    name: str              # "jobs.total" | "queue.depth" | "workers.idle" | ...
    value: float
    labels: dict[str, str]  # {"stratum": "S4", "component": "ControlPlane"}
    timestamp: float
```

### Sinks

| Sink | Transport | Use |
|------|-----------|-----|
| `StdoutSink` | NDJSON to `stdout` | Default production sink |
| `CollectingSink` | In-memory list | Tests |

### Invariant

`emit_metric()` is guaranteed to never block and never raise:

```python
def emit_metric(event: MetricEvent) -> None:
    try:
        for sink in _sinks:
            sink.emit(event)
    except Exception:
        pass  # safety guard
```

---

## Tracing

File: `src/platform/observability/tracing.py`

### Three-Tier Trace Model

```
┌─────────────────────────────────────────────────────┐
│  Job Trace (root)                                    │
│  trace_id = _root_trace_id(correlation_id)           │
│  ┌─────────────────────────────────────────────────┐ │
│  │ Cycle Trace (per execution cycle)                │ │
│  │ parent_trace_id = job trace_id                   │ │
│  │ ┌─────────────────────────────────────────────┐  │ │
│  │ │ Segment Trace (per logical step)            │  │ │
│  │ │ parent_trace_id = cycle trace_id            │  │ │
│  │ └─────────────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### TraceEvent

```python
@dataclass(frozen=True)
class TraceEvent:
    trace_type: str         # "job" | "cycle" | "segment"
    trace_id: str
    parent_trace_id: str | None
    correlation_id: str | None
    timestamp: float
    component: str
    fields: dict[str, Any]
```

### TraceContext

Context manager that propagates `correlation_id` via `threading.local()`:

```python
with TraceContext(correlation_id="corr-123"):
    emit_job_trace("deploy")        # auto-attaches correlation_id
    emit_cycle_trace("planning")    # linked via parent_trace_id
    emit_segment_trace("fetch")     # linked to cycle
```

The `_root_trace_id()` function caches the stable root trace ID per
`correlation_id`, ensuring all traces for the same correlation share one root.

---

## Health Checks

File: `src/platform/observability/health.py`

| Check | Function | Returns |
|-------|----------|---------|
| **Liveness** | `check_liveness()` | HealthResponse with daemon + event substrate status |
| **Readiness** | `check_readiness()` | Queue depth, worker health, panic guard status |
| **Worker pool** | `check_worker_pool_health()` | Detailed per-worker info |

All checks support pluggable callable registrations:

```python
register_readiness_check("custom", lambda: HealthResponse(ok=True))
```

---

## Dashboard

File: `src/platform/observability/dashboard/web_server.py`

An **in-memory, read-only** event dashboard:

| Route | Purpose |
|-------|---------|
| `GET /api/state` | Current application state snapshot |
| `GET /api/summary` | Aggregate metrics summary |
| `GET /api/events/stream` | Server-sent events (SSE) live stream |
| `GET /api/events/recent` | Recent event log |

- `DashboardEventStore` derives state from incoming JSON-line events.
- Never mutates S4 state — read-only access.
- `DashboardHTTPHandler` implements the HTTP routing inline.

---

## Related Documents

- [CONTROL_PLANE.md](CONTROL_PLANE.md) — Metric/trace emission on transitions
- [WORKER_POOL.md](WORKER_POOL.md) — Heartbeat metrics
- [LIFECYCLE.md](LIFECYCLE.md) — State machine instrumentation points
- [DEPLOYMENT.md](DEPLOYMENT.md) — Observability in container vs local
