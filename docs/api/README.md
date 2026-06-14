# S4 Agent Runtime — API Documentation

## Design Philosophy

The vai-core (Stratum-4) API is built around **contracts over implementations**.
Every component exposes a narrow, stable public surface — never leaking internal
representations, never raising exceptions where a structured result suffices,
and always terminating through a well-defined return type.

Key principles:

1. **Functions, not classes** — public entrypoints are plain functions
   (e.g. `load_config()`, `run_release_checklist()`, `emit_metric()`).
   Classes are implementation details unless they model a value object
   (e.g. `S4Config`, `SecurityResult`, `ReleaseReport`).

2. **Structured results over exceptions** — the security layer and release
   checklist return dataclass result objects (`SecurityResult`, `ReleaseReport`)
   with `ok`/`passed` booleans. This forces callers to handle failure
   explicitly.

3. **Read-only by default** — `S4Config` is immutable after construction.
   Mutation raises `TypeError`. This eliminates a whole class of
   concurrency bugs.

4. **Never block, never raise** — the observability layer (`log()`,
   `emit_metric()`, `emit_trace()`) is designed to never block the caller
   and never propagate exceptions. Safe to call from any thread.

5. **Sink-based extensibility** — logging, metrics, and tracing use a
   `*Sink` protocol. Swap the backend (stdout → Prometheus → OTEL) by
   registering a different sink — no code changes needed.

---

## API Endpoints by Component

### Configuration (`config_system`)

| Function | Signature | Purpose |
|---|---|---|
| `load_config` | `(config_file=None, overrides=None) -> S4Config` | Load, validate, return immutable config |
| `S4Config.get` | `(key: str) -> Any` | Dotted-key access (e.g. `"workers.count"`) |
| `S4Config.to_dict` | `() -> dict` | Deep-copy the full config |

### Security (`hardening`)

| Function | Signature | Purpose |
|---|---|---|
| `check_auth` | `(request, *, enabled, token) -> SecurityResult` | Verify bearer token or X-Auth-Token |
| `check_rate_limit` | `(limiter, client_id, *, enabled) -> SecurityResult` | Fixed-window rate limit check |
| `validate_input` | `(payload, schema=None, *, max_size) -> SecurityResult` | Schema-based input validation |
| `validate_job_payload` | `(payload) -> SecurityResult` | Validate standard S4 job schema |
| `validate_instruction` | `(instruction) -> SecurityResult` | Validate daemon instruction format |
| `sandbox_execute` | `(fn, timeout_ms, config) -> SecurityResult` | Time-bounded, resource-limited execution |

### Observability (`observability`)

| Function | Module | Purpose |
|---|---|---|
| `log()` | `logging` | Emit structured log event |
| `emit_metric()` | `metrics` | Emit numeric metric |
| `emit_trace()` | `tracing` | Emit hierarchical trace event |
| `check_liveness()` | `health` | Is the daemon running? |
| `check_readiness()` | `health` | Can the daemon accept jobs? |
| `check_worker_pool_health()` | `health` | Is the worker pool healthy? |

### Queue (`queue`)

| Method | Signature | Purpose |
|---|---|---|
| `push` | `(job: Job) -> str` | Enqueue a job, return its ID |
| `pop` | `() -> Job | None` | Dequeue oldest job (lease) |
| `acknowledge` | `(job_id: str) -> None` | Mark job processed |
| `requeue` | `(job_id: str) -> None` | Return job to front for retry |
| `nack` | `(job_id: str) -> None` | Dead-letter the job |

### Worker Pool (`pool`)

| Method | Signature | Purpose |
|---|---|---|
| `start()` | `() -> None` | Spawn all workers and optional supervisor |
| `stop()` | `() -> None` | Signal shutdown |
| `join()` | `() -> None` | Wait for all threads to finish |
| `create_worker_pool` | `(config: WorkerPoolConfig) -> WorkerPool` | Factory function |

### Supervision (`supervisor`)

| Component | Class | Purpose |
|---|---|---|
| Worker supervisor | `SupervisorLoop` | Monitors heartbeats, restarts unhealthy workers |
| Queue supervisor | `QueueSupervisor` | Detects stuck jobs and backpressure |
| Control plane | `ControlPlaneSupervisor` | Cross-service lifecycle correctness |

### Instruction Dispatch (`instruction_dispatch`)

| Method | Signature | Purpose |
|---|---|---|
| `dispatch()` | `(instruction, action_map_override) -> (action, event)` | Map instruction type → daemon action |
| `validate()` | `(instruction) -> dict` | Validate instruction schema (raises on failure) |

### Deployment (`deployment`)

| Function | Signature | Purpose |
|---|---|---|
| `run_target` | `(mode: str) -> None` | Run S4 in local or container mode |

### Release (`checklist`)

| Function | Signature | Purpose |
|---|---|---|
| `run_release_checklist` | `(component_versions=None) -> ReleaseReport` | Run all 7 check categories |

---

## Authentication Model

Auth is **optional** and configured via the `auth` section of `S4Config`:

```yaml
auth:
  enabled: true       # default: false
  token: "my-secret"  # default: ""
```

When `auth.enabled` is `True`, incoming requests must present the token
via one of four locations (checked in order):

1. `Authorization: Bearer <token>` header
2. `X-Auth-Token: <token>` header
3. `params.token` (query string)
4. `body.token` (request body)

When `auth.enabled` is `False` (the default), `check_auth()` returns
`SecurityResult(ok=True)` unconditionally — every request is allowed.

---

## Validation Schema

Input validation uses a recursive schema format shared between the config
system and the security layer. A schema is a dict with optional keys:

| Key | Type | Purpose |
|---|---|---|
| `type` | Python type | Expected type (`dict`, `list`, `str`, `int`, `bool`) |
| `fields` | `dict[str, schema]` | Sub-field schemas (for `dict` type) |
| `items` | `schema` | Item schema (for `list` type) |
| `valid_values` | `list` | Allowed values (for `str` type) |
| `item_valid_values` | `list` | Allowed values for each list item |
| `optional` | `bool` | If `True`, field may be absent (default: required) |

---

## Structured Result Types

### SecurityResult

```python
@dataclass
class SecurityResult:
    ok: bool
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
```

Never raised — always returned. Callers check `result.ok`:

```python
result = check_auth(request, enabled=True, token=cfg.get("auth.token"))
if not result.ok:
    return SecurityResult(
        ok=False,
        error=result.error,
        details=result.details,
    )
```

### HealthResponse

```python
@dataclass(frozen=True)
class HealthResponse:
    status: str      # "ok" | "degraded" | "unhealthy"
    timestamp: str   # ISO-8601
    component: str   # e.g. "s4", "worker_pool"
    details: dict[str, str]
```

### ReleaseReport

```python
@dataclass
class ReleaseReport:
    passed: bool
    failures: list[CheckResult]
    warnings: list[CheckResult]
    started_at: str
    completed_at: str
    component_versions: dict[str, str]
```

### CheckResult

```python
@dataclass
class CheckResult:
    name: str
    passed: bool
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
```

---

## Error Handling Invariants

| Layer | Strategy |
|---|---|
| Configuration | Raises `ConfigError` / `ConfigValidationError` — structural errors must fail fast |
| Security | Never raises — always returns `SecurityResult` |
| Observability | Never raises — top-level `try/except pass` guards every public function |
| Queue | Raises on misuse (e.g. ack unknown ID) — follows standard Python |
| Release | Never raises — collects all failures into `ReleaseReport` |

## Cross-Cutting Concerns

- **Correlation IDs** — propagated via `LogContext` / `TraceContext` context
  managers. Thread-local; automatically injected into log and trace events.
- **Component names** — optional string attached to log, trace, and health
  events for routing and filtering.
- **Sink registration** — all three observability channels support
  `register_*_sink()` / `clear_*_sinks()` for testability.
