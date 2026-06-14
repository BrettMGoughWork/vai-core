# Release Checklist API — S4.9.7

**Module:** `src.release.checklist`

The release checklist system verifies that an S4 build is safe to ship. It
runs 7 categories of local (no-network) checks and aggregates results into
a single `ReleaseReport`. All checks are read-only — they never modify state
or depend on external services.

---

## `run_release_checklist()`

```python
def run_release_checklist(
    component_versions: dict[str, str] | None = None,
) -> ReleaseReport:
```

Run all release checks and return a comprehensive report.

### Args / Returns / Raises

| Category | Detail |
|---|---|
| `component_versions` | Optional dict mapping component names to version strings (e.g. `{"s4-core": "1.2.3", "s4-daemon": "1.2.3"}`). Recorded in the report for traceability. |
| Returns | A `ReleaseReport` with aggregated results from all 7 check categories. |
| Raises | **Never.** All failures are captured in the report. |

### Example

```python
from src.release.checklist import run_release_checklist

report = run_release_checklist({
    "s4-core": "2.1.0",
    "s4-daemon": "2.1.0",
    "observer": "1.0.0",
})

if not report.passed:
    print(f"Release BLOCKED — {len(report.failures)} failures")
    for f in report.failures:
        print(f"  ❌ {f.name}: {f.error}")
else:
    print(f"Release PASSED — {report.total_checks} checks")
```

---

## `ReleaseReport` — Results

```python
@dataclass
class ReleaseReport:
    passed: bool
    failures: list[CheckResult]
    warnings: list[CheckResult]
    started_at: str               # ISO-8601
    completed_at: str             # ISO-8601
    component_versions: dict[str, str]
```

### Properties

| Property | Type | Description |
|---|---|---|
| `passed` | `bool` | `True` only if every check passed (no failures, warnings allowed) |
| `failures` | `list[CheckResult]` | Checks that failed — these block the release |
| `warnings` | `list[CheckResult]` | Checks that passed with non-blocking observations |
| `started_at` | `str` | ISO-8601 timestamp when checks began |
| `completed_at` | `str` | ISO-8601 timestamp when checks completed |
| `component_versions` | `dict[str, str]` | Versions passed at call time (empty dict when omitted) |
| `total_checks` | `int` | Computed property: `len(failures) + len(warnings) + passed_checks` |

---

## `CheckResult` — Single Check

```python
@dataclass
class CheckResult:
    name: str                      # Human-readable check name
    passed: bool                   # Did this specific check pass?
    error: str | None = None       # Failure description (if not passed)
    details: dict[str, Any] = field(default_factory=dict)
```

---

## The 7 Check Categories

### 1. Invariant Checks

Verify that core data structures and model invariants hold at runtime.

| Check | Description |
|---|---|
| `invariants` | Runs property-based tests on key data structures (configuration, supervisor events, queue items). Checks: field presence, type correctness, default value application, immutability guarantees, and round-trip serialization. Fails if any invariant is violated. |

### 2. Determinism Checks

Verify that functions with the same inputs produce the same outputs.

| Check | Description |
|---|---|
| `determinism` | Runs pairs of identical calls through deterministic functions (`load_config`, `emit_metric`, `emit_trace`, `check_health`, security validators). Compares outputs field-by-field. Fails if any pair diverges. Warns if JSON serialization fidelity is lossy. |

### 3. Safety Checks

Verify that the safety layer handles all inputs correctly.

| Check | Description |
|---|---|
| `safety` | Tests `validate_input`, `validate_job_payload`, and `validate_instruction` with valid, invalid, and boundary inputs. Tests `sandbox_execute` timing out, completing normally, and raising. Tests auth with matching, missing, and wrong tokens. Each test is a separate `CheckResult`. Fails if any safety invariant is violated. |

### 4. Performance Checks

Verify that key operations complete within acceptable time bounds.

| Check | Description |
|---|---|
| `performance_bound` | Measures wall-clock time for config loading, input validation, rate limiting (100 checks), sandbox execute of a fast operation, logging, metric emission, and trace emission. Each operation iterates `N` times and measures single-call and total duration. Fails if any operation exceeds its per-call threshold. |

### 5. Concurrency Checks

Verify that threaded components do not corrupt shared state.

| Check | Description |
|---|---|
| `concurrency_safety` | Runs concurrent calls from multiple threads into `RateLimiter`, `InMemoryQueue`, logger, metrics, and tracer. Verifies no assertion violations or data corruption. Fails if any concurrent mutation produces incorrect counts or panics. |

### 6. Channel Checks

Verify that the observability event sinks receive correctly structured events.

| Check | Description |
|---|---|
| `channel_output` | Registers test sinks, emits log/metric/trace events, then validates the captured output against expected schemas. Verifies event field presence, data types, and ordering. Fails if an event is missing, malformed, or out of order. |

### 7. Observability Checks

Verify that all observability entrypoints resolve without error.

| Check | Description |
|---|---|
| `observability` | Calls every public function in `logging`, `metrics`, `tracing`, and `health` modules. Verifies no exceptions escape. Tests sink registration and clearing, context managers (LogContext, TraceContext), health check registration, and mark_shutdown. Fails if any call raises. |

---

## Error Handling Strategy

All errors are **captured, not thrown**:

```
run_release_checklist()
  ├─ _check_invariants()         → list[CheckResult]  ← never raises
  ├─ _check_determinism()        → list[CheckResult]  ← never raises
  ├─ _check_safety()             → list[CheckResult]  ← never raises
  ├─ _check_performance_bound()  → list[CheckResult]  ← never raises
  ├─ _check_concurrency_safety() → list[CheckResult]  ← never raises
  ├─ _check_channel_output()     → list[CheckResult]  ← never raises
  └─ _check_observability()      → list[CheckResult]  ← never raises
```

Each `_check_*` function wraps its internal logic in `try/except` and returns
`[CheckResult(name, passed=False, error=str(e))]` on any unexpected failure.
This guarantees that a single broken check never blocks the remaining 6
categories.

---

## Invariants

1. **No network access** — all checks are local. Zero external dependencies.
2. **No state mutation** — checks never modify global state. Dependencies
   (queues, rate limiters) are created fresh for each check.
3. **Deterministic** — `run_release_checklist()` with the same component
   versions always produces the same report.
4. **Fully aggregated** — every check, pass or fail, is captured in the
   report. No partial results.
5. **Self-contained** — the module can be imported and run in isolation.
   Ideal for CI pipelines and pre-deploy gating.
