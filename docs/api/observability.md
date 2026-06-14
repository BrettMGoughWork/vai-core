# Observability API — S4.9.4

**Package:** `src.platform.observability`

The observability package provides structured logging, metrics collection,
distributed tracing, and health checking. All three channels (log, metric,
trace) follow the same architecture: a dataclass event type, a Protocol sink,
a global sink registry, and public emit functions.

---

## Logging (`src.platform.observability.logging`)

### `log()`

```python
def log(
    level: str,
    message: str,
    fields: dict[str, Any] | None = None,
    component: str | None = None,
) -> LogEvent | None:
```

Emit a structured log event. Never raises — failures are silently caught.

#### Standardised Levels

| Level | When to Use |
|---|---|
| `"debug"` | Detailed diagnostic information |
| `"info"` | Normal operational events |
| `"warning"` | Unexpected but handled conditions |
| `"error"` | Recoverable failures |
| `"critical"` | Unrecoverable failures requiring immediate action |

#### LogEvent Structure

```python
@dataclass
class LogEvent:
    timestamp: str        # ISO-8601
    level: str
    message: str
    fields: dict          # automatically includes correlation_id, trace_id
    component: str | None
```

#### Category Helpers

These convenience functions wrap `log()` with a fixed level and structured
fields, providing domain-specific signatures:

| Function | Signature | Level |
|---|---|---|
| `log_job_state_transition` | `(job_id, from_state, to_state, component, metadata) -> None` | `"info"` |
| `log_worker_activity` | `(worker_id, action, component, metadata) -> None` | `"info"` |
| `log_queue_event` | `(queue, event_type, job_id, component, metadata) -> None` | `"info"` |
| `log_execution` | `(action, duration_ms, status, component, metadata) -> None` | `"info"` |
| `log_supervisor_action` | `(supervisor_id, action, target, component, metadata) -> None` | `"info"` |

#### LogContext — Correlation and Trace ID Injection

```python
from src.platform.observability.logging import LogContext

with LogContext(correlation_id="req-123", trace_id="trace-abc"):
    log("info", "Processing job", {"job_id": "job-1"})
    # All log events within this block automatically include
    # correlation_id="req-123" and trace_id="trace-abc" in their fields.
```

Inherited via thread-local storage. Child threads **do not** inherit the
parent's `LogContext` automatically.

---

### Sink Registration

```python
from src.platform.observability.logging import register_log_sink, clear_log_sinks

register_log_sink(StdoutLogSink())
clear_log_sinks()  # for testing — resets to no-op
```

Each registered sink receives every `LogEvent`. Default sink: `StdoutLogSink`.

---

## Metrics (`src.platform.observability.metrics`)

### `emit_metric()`

```python
def emit_metric(
    name: str,
    value: float | int,
    labels: dict[str, str] | None = None,
) -> MetricEvent | None:
```

Emit a numeric metric observation. Never raises.

#### MetricEvent Structure

```python
@dataclass
class MetricEvent:
    timestamp: str         # ISO-8601
    name: str
    value: float | int
    labels: dict[str, str]
```

#### Usage

```python
from src.platform.observability.metrics import emit_metric

emit_metric("jobs_processed", 1, {"queue": "default"})
emit_metric("request_duration_ms", 342.5, {"endpoint": "/v1/execute"})
```

Metrics are emission-only — no aggregation is performed at the library level.
Downstream exporters (Prometheus, etc.) handle bucketing and aggregation.

#### Sink Registration

```python
from src.platform.observability.metrics import register_metric_sink, clear_metric_sinks

register_metric_sink(StdoutMetricSink())
```

---

## Tracing (`src.platform.observability.tracing`)

### `emit_trace()`

```python
def emit_trace(
    trace_type: str,
    fields: dict[str, Any],
    *,
    parent_trace_id: str | None = None,
    component: str | None = None,
) -> str | None:
```

Emit a hierarchical trace event. Returns the generated `trace_id` (a UUID
string) or `None` if emission failed. Never raises.

#### TraceEvent Structure

```python
@dataclass
class TraceEvent:
    timestamp: str           # ISO-8601
    trace_id: str            # UUID v4
    parent_trace_id: str | None
    trace_type: str
    fields: dict
    component: str | None
```

#### Trace Hierarchy (Stable Root IDs)

The tracing module reserves three root-level trace types that produce stable
root IDs deterministically derived from the correlation ID:

| Trace Type | When to Use | Root ID Derivation |
|---|---|---|
| `"job"` | A complete job execution | `uuid5(correlation_id)` |
| `"cycle"` | A supervisor cycle | `uuid5(correlation_id + "-cycle")` |
| `"segment"` | A segment within a cycle | `uuid5(correlation_id + f"-{idx}")` |

#### Category Helpers

```python
from src.platform.observability.tracing import (
    emit_job_trace,
    emit_cycle_trace,
    emit_segment_trace,
)

emit_job_trace(job_id, "start", {"input_size": 2048})
emit_cycle_trace(cycle_id, "begin", {"queue_depth": 42})
emit_segment_trace(segment_id, "execute", {"action": "transform"})
```

#### TraceContext

```python
from src.platform.observability.tracing import TraceContext

with TraceContext(trace_type="job", fields={"job_id": "j-1"}):
    emit_trace("segment", {"action": "process"})
    # Auto-injects parent_trace_id from context
```

---

## Health Checks (`src.platform.observability.health`)

### HealthResponse

```python
@dataclass(frozen=True)
class HealthResponse:
    status: str      # "ok" | "degraded" | "unhealthy"
    timestamp: str   # ISO-8601
    component: str   # e.g. "s4", "worker_pool"
    details: dict[str, str]
```

### `check_liveness()`

```python
def check_liveness() -> HealthResponse:
```

Quick liveness probe — verifies the daemon process is running and the
observability module initialised. Returns `HealthResponse(status="ok"`).

### `check_readiness()`

```python
def check_readiness() -> HealthResponse:
```

Comprehensive readiness check. Calls all registered delegates (queue depth,
supervisor health, etc.). If any delegate is registered but has never been
called, status is `"degraded"`. If any delegate fails, status is `"unhealthy"`.

All details are aggregated into a single response.

### `check_worker_pool_health()`

```python
def check_worker_pool_health() -> HealthResponse:
```

Check worker pool state. Verifies:
- Workers are alive and have recent heartbeats
- Pool is not in shutdown state
- Supervisor has no fatal errors

### Registration API

```python
from src.platform.observability.health import (
    init_health,
    mark_shutdown,
    register_queue_depth,
    register_supervisor_health,
)

init_health()                          # Reset to default state
mark_shutdown()                        # Mark daemon as shutting down
register_queue_depth(lambda: q.depth())  # Register depth query
register_supervisor_health(lambda: supervisor.report())
```

---

## Invariants

1. **Never raises** — `log()`, `emit_metric()`, and `emit_trace()` catch all
   exceptions internally and return `None` on failure.
2. **Thread-local context** — `LogContext` and `TraceContext` are thread-local.
   Children must establish their own context.
3. **Synchronous emission** — events are emitted synchronously on the calling
   thread. Exporters that need async I/O should buffer internally.
4. **Default no-ops** — with no sinks registered, all emit functions silently
   become no-ops. The system works without observability.
5. **Fixed trace root IDs** — job/cycle/segment root IDs are deterministic
   UUIDs derived from the correlation ID, enabling cross-session correlation
   without a distributed coordinator.
