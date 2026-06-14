# Boundaries — Stratum Isolation and Invariants

**Purpose:** Define the formal boundaries, import rules, and architectural invariants that govern all five strata of the vai-core runtime.

---

## Strata Overview

| Stratum | Directory           | Responsibility                                      |
|---------|---------------------|-----------------------------------------------------|
| S1      | `src/runtime/`      | Execution engine, pipeline, retry, recovery         |
| S2      | `src/strategy/`     | Planning, memory, task decomposition                |
| S3      | `src/capabilities/` | Primitives, skills, registry                        |
| S4      | `src/platform/`     | Queue, supervision, control plane, daemon, channels |
| S5      | `src/agent/`        | Agents, workflows, router, supervisor               |

---

## Import Acyclicity Rules

The dependency graph between strata is a strict DAG. Violations are build errors.

```
S1 ← S2 ← S3 ← S4 → S5
```

| Rule | Description |
|------|-------------|
| **S4 → S2** | S4 **must not** import S2. The control plane dispatches instructions to S2 via the adapter layer, never by importing S2 modules directly. |
| **S4 → S5** | S4 **must not** import S5. S5 subscribes to S4 events; S4 has no knowledge of S5. |
| **S2 → S1** | S2 can import S1 utilities (e.g. primitive types). |
| **S3 → S2** | S3 can import S2 for strategy context. |
| **S1 ↔ S0** | No stratum below S1 exists. S1 is leaf code. |

```python
# ControlPlane (S4) — NO imports from S2, or S5
from src.platform.runtime.job_state import JobState, transition  # ✓ same stratum
from src.platform.observability.logging import log_job_state_transition  # ✓ same stratum
from src.platform.supervisor.system_alerts import alert_async  # ✓ same stratum
```

---

## Purity Requirements (S2)

S2 (strategy) must be **pure logic**. No IO, no side effects, no mutable shared state.

- Functions are deterministic: same inputs → same outputs.
- No file system, network, or database access.
- No `threading`, `multiprocessing`, or `asyncio` event loops.
- No imports from `requests`, `aiohttp`, `sqlite3`, `pathlib`, `os`, `sys`.
- All state is passed in as arguments and returned as values.
- Pure functions are testable without fixtures, mocks, or setup.

**Rationale:** S2 is the reasoning core. Conflating logic with IO makes planning
non-deterministic and untestable.

---

## Config Immutability

`S4Config` (in `src/platform/config/config_system.py`) is **read-only** by design.

```python
# TypeError at runtime on mutation
config = load_config()
config["workers.count"] = 4  # raises TypeError
```

- Config is a 4-layer merge: defaults → YAML file → env vars → runtime overrides.
- The merge produces an immutable snapshot at startup.
- All strata read from the same immutable config tree.
- No component can mutate config at runtime.

---

## Panic/Poison Isolation Boundaries

**PanicGuard** (`src/platform/runtime/safety/panic_guard.py`) is pure logic —
it wraps a callable and catches all exceptions into a `StructuredFailure` envelope.

```
 Worker Pipeline (S4)
 ┌────────────────────────────┐
 │ CrashRecoveryStage         │  ← catches all exceptions
 │   → wraps in PanicDecision│
 │ IdempotencyStage           │
 │ DegradedModeStage          │
 │ ExecutionStage             │
 └────────────────────────────┘
         ↓ failure
 ControlPlane (S4)
 ┌────────────────────────────┐
 │ mark_failed() / mark_poison() │
 │   → job_state.transition() │
 │   → emit metric & trace    │
 │   → system_alert_async()   │
 └────────────────────────────┘
```

- A **poison** job has exceeded `max_consecutive_failures` and is terminal.
- PanicGuard **never** mutates state — it returns a decision record.
- The control plane applies the decision (state transition, alert).
- S1/S2/S3 cannot access PanicGuard directly.

---

## No Silent Fallback Rule

No S4 component may silently produce incorrect output when a subsystem fails.

| Violation Example | Correct Behaviour |
|------------------|-------------------|
| Catch exception, return `None` | Return `PanicDecision` or `StructuredFailure` |
| Skip metric emission on error | `emit_metric()` wraps in `try/except` and never raises |
| Log and continue with stale data | Set `status=poison` and escalate |

The only allowed silent behaviour is the safety guard on `emit_metric()` /
`emit_trace()` / `alert_async()` — these must never raise and never block.

---

## Related Documents

- [EVENT_SUBSTRATE.md](EVENT_SUBSTRATE.md) — Queue delivery guarantees
- [CONTROL_PLANE.md](CONTROL_PLANE.md) — State transition authority
- [WORKER_POOL.md](WORKER_POOL.md) — Thread isolation
- [LIFECYCLE.md](LIFECYCLE.md) — State machines and poison path
- [DEPLOYMENT.md](DEPLOYMENT.md) — Configuration sourcing
