# Security API — S4.9.3

**Module:** `src.platform.security.hardening`

Enforces baseline safety guarantees across all S4 components. Every public
function returns a `SecurityResult` and **never** raises an exception to
the caller.

---

## Core Return Type: `SecurityResult`

```python
@dataclass
class SecurityResult:
    ok: bool
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
```

| Field | Type | Description |
|---|---|---|
| `ok` | `bool` | `True` if the check passed |
| `error` | `str | None` | Human-readable error description (non-None only when `ok` is `False`) |
| `details` | `dict` | Machine-readable details (e.g. `{"reason": "timeout"}`) |

**Rule:** Callers **must** check `result.ok` before proceeding:

```python
result = check_auth(request, enabled=True, token="xyz")
if not result.ok:
    # result.error is safe to use here
    return result
```

---

## `check_auth()`

```python
def check_auth(
    request: dict[str, Any],
    *,
    enabled: bool = False,
    token: str = "",
) -> SecurityResult:
```

Verify that a request carries a valid static authentication token.

### Token Source (checked in order)

1. `Authorization: Bearer <token>` header
2. `X-Auth-Token: <token>` header
3. `params.token` (query parameters)
4. `body.token` (request body)

### Request Format

```python
request = {
    "headers": {
        "authorization": "Bearer abc123",
    },
    "params": {},
    "body": {},
}
```

### Behaviour Matrix

| `enabled` | Token Match | Result |
|---|---|---|
| `False` | N/A | `SecurityResult(ok=True)` — all requests pass |
| `True` | Matches | `SecurityResult(ok=True)` |
| `True` | Missing | `SecurityResult(ok=False, error="Authentication required", details={"reason": "missing_token"})` |
| `True` | Wrong | `SecurityResult(ok=False, error="Invalid authentication token", details={"reason": "invalid_token"})` |

---

## `RateLimiter` and `check_rate_limit()`

```python
class RateLimiter:
    def __init__(self, max_requests_per_minute: int = 60) -> None: ...
    def check(self, client_id: str) -> SecurityResult: ...
    def reset(self, client_id: str | None = None) -> None: ...

def check_rate_limit(
    limiter: RateLimiter,
    client_id: str,
    *,
    enabled: bool = True,
) -> SecurityResult:
```

In-memory fixed-window rate limiter with 60-second windows. Thread-safe.

### Behaviour

| `enabled` | Under Limit | Result |
|---|---|---|
| `False` | N/A | `SecurityResult(ok=True)` |
| `True` | Yes | `SecurityResult(ok=True)` |
| `True` | No | `SecurityResult(ok=False, error="Rate limit exceeded", details={"reason": "rate_limited", "retry_after": 12.5, "limit": 60, "window_seconds": 60})` |

The `retry_after` field (in seconds) tells callers when to retry.

### Usage

```python
from src.platform.security.hardening import RateLimiter, check_rate_limit

limiter = RateLimiter(max_requests_per_minute=30)

# In request handler:
result = check_rate_limit(limiter, client_id="user-42", enabled=True)
if not result.ok:
    return {"error": "too many requests", "retry_after": result.details["retry_after"]}
```

### State Management

| Method | Behaviour |
|---|---|
| `reset(client_id)` | Clear the window for one client |
| `reset()` | Clear all windows |

---

## `validate_input()`

```python
def validate_input(
    payload: Any,
    schema: dict[str, Any] | None = None,
    *,
    max_size: int = 1024 * 1024,  # 1 MB
) -> SecurityResult:
```

Validate an arbitrary payload against an optional schema.

### Validation Pipeline

1. **Must be a mapping** — non-dict payloads fail immediately.
2. **Size check** — JSON-serialised payload must not exceed `max_size` bytes.
3. **Schema validation** — if `schema` is provided, every field is recursively
   checked for type, presence, and valid values.

### Schema Format

```python
{
    "type": dict,                          # expected Python type
    "fields": {                            # sub-field definitions
        "name": {"type": str},
        "count": {"type": int},
        "status": {
            "type": str,
            "valid_values": ["active", "inactive"],
            "optional": True,              # default: required
        },
    },
    "items": {"type": str},               # for list types
    "valid_values": ["a", "b"],           # value constraint
}
```

### Error Details

On failure, `details` contains `{"errors": ["list of error messages"]}`:

```python
SecurityResult(ok=False, error="Validation failed",
    details={"errors": ["name: expected str, got int", "count: missing required field"]})
```

---

## `validate_job_payload()`

```python
def validate_job_payload(payload: dict[str, Any]) -> SecurityResult:
```

Validate a job payload against the standard S4 job schema.

### Schema

| Field | Type | Required | Valid Values |
|---|---|---|---|
| `job_id` | `str` | Yes | — |
| `job_type` | `str` | Yes | `process_message`, `run_tool`, `execute_workflow`, `handle_event`, `run_cycle`, `health_check` |
| `instructions` | `list` | No | — |
| `payload` | `dict` | No | — |
| `metadata` | `dict` | No | — |

### Example

```python
result = validate_job_payload({
    "job_id": "job-abc-123",
    "job_type": "process_message",
    "instructions": [{"type": "execute", "params": {"cmd": "ls"}}],
})
```

---

## `validate_instruction()`

```python
def validate_instruction(instruction: Any) -> SecurityResult:
```

Validate a single instruction object.

### Schema

| Field | Type | Required | Valid Values |
|---|---|---|---|
| `type` | `str` | Yes | `execute`, `query`, `transform`, `validate`, `generate`, `summarize`, `route` |
| `params` | `dict` | No | — |
| `timeout_ms` | `int` | No | — |

---

## `sandbox_execute()`

```python
@dataclass
class SandboxConfig:
    allowed_paths: list[str] = field(default_factory=lambda: [os.getcwd()])
    allow_network: bool = False
    allow_subprocess: bool = False
    max_memory_mb: int = 256

def sandbox_execute(
    fn: Callable[[], Any],
    timeout_ms: int = 30000,
    config: SandboxConfig | None = None,
) -> SecurityResult:
```

Execute a callable in a sandboxed context with a timeout.

### Safety Mechanisms

| Mechanism | Description |
|---|---|
| **Time limit** | Thread capped at `timeout_ms` (primary protection) |
| **Filesystem** | Restricted to `allowed_paths` (config declaration) |
| **Network** | Disabled unless `allow_network` is set |
| **Subprocess** | Disabled unless `allow_subprocess` is set |

### Return Scenarios

| Outcome | Result |
|---|---|
| Function completes within timeout | `SecurityResult(ok=True, details={"result": <return_value>})` |
| Function times out | `SecurityResult(ok=False, error="Execution timed out after 5000ms", details={"reason": "timeout", "timeout_ms": 5000})` |
| Function raises | `SecurityResult(ok=False, error="Sandbox execution failed: <exception>" , details={"reason": "execution_error"})` |

### Usage

```python
result = sandbox_execute(lambda: run_job(job), timeout_ms=10000)
if result.ok:
    output = result.details["result"]
```

---

## Invariants

1. **No exceptions** — every function returns `SecurityResult`. Callers never
   need `try/except`.
2. **Thread-safe** — `RateLimiter` uses `threading.Lock`. `sandbox_execute()`
   uses `threading.Thread` with daemon threads.
3. **Optional enforcement** — auth and rate limiting can be disabled at
   runtime via `enabled=False`. Disabled checks always pass.
4. **Self-cleaning** — rate limiter prunes expired entries on every check.
5. **Deterministic input validation** — same payload + schema always produces
   the same result.
