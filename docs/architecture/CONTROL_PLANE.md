# Control Plane — Job Lifecycle Authority

**Purpose:** Central authority for job registration, state transitions,
heartbeat monitoring, and supervision integration. Synchronous,
single-threaded, and minimal.

File: `src/platform/runtime/control_plane.py`

---

## Responsibilities

| Responsibility | Method | Description |
|---------------|--------|-------------|
| **Job registry** | `register_job()` | Accept a new `Job`, validate, assign ID, persist |
| **Instruction dispatch** | `dispatch_instruction()` | Route incoming instructions via `UnifiedInstructionDispatcher` |
| **State transitions** | `mark_running/succeeded/failed/poison()` | Validate and persist state changes |
| **Supervision** | `collect_heartbeat()`, `evaluate()` | Forward heartbeats to embedded `SupervisorLoop` |
| **Heartbeat monitoring** | `accept_heartbeat()` | Record worker heartbeat via `HeartbeatMonitor` |

---

## Job Lifecycle States

```
         ┌──────────────────┐
         │    PENDING       │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
    ┌───│    RUNNING        │
    │   └──┬────┬────┬──────┘
    │      │    │    │
    │      ▼    ▼    ▼
    │  ┌────┐ ┌──┐ ┌─────┐
    │  │SUC-│ │FA│ │POI- │
    │  │CEED│ │IL│ │SON  │
    │  │ED  │ │ED│ │     │
    │  └────┘ └──┘ └─────┘
    │   terminal   terminal
    │
    └── retry → PENDING
```

Transitions validated by `job_state.transition()` — raises `ValueError` for
illegal transitions. `POISON` is terminal: no outgoing transitions.

---

## Supervision Model

### Queue Supervisor (`src/platform/supervisor/queue_supervisor.py`)

- **Diagnostic, not agentic.** Monitors queue health at a fixed interval.
- Detects stuck jobs (exceeded allowed processing window) and queue backpressure.
- Emits structured events — never modifies job state.

| Event | Condition |
|-------|-----------|
| `job_stuck` | Job in `pending` or `running` beyond timeout |
| `queue_backpressure` | Queue depth exceeds threshold |
| `queue_supervisor_escalation` | Repeated backpressure detects |

### Control Plane Supervisor (`src/platform/supervisor/control_plane_supervisor.py`)

- **Stateless, idempotent.** Evaluates S2/S3/S4 state snapshots for inconsistencies.
- 6 checks, 4 auto-repairs, escalation when repair is impossible.
- Configurable `max_inconsistencies_per_window` (default 10 in 60s).

### Supervisor Loop (`src/platform/supervisor/supervisor_loop.py`)

- Runs on fixed interval, manages worker lifecycle.
- Collects heartbeats, evaluates health, applies restart decisions.
- Does **not** execute jobs — only manages worker lifecycle.

---

## Panic Guard Integration

```
Worker Pipeline → PanicGuard.wrap(callable)
                       ↓
            ┌─────────────────────┐
            │ StructuredFailure?  │──→ PanicDecision
            │                     │
            │ Normal return?      │──→ Success value
            └─────────────────────┘
                       ↓
              ControlPlane.mark_failed()
              or .mark_poison()
```

`PanicGuard` is pure logic — it never mutates state. The control plane applies
the state transition and emits alerts.

---

## Degraded Mode Transitions

```
Normal ──→ Degraded ──→ Recovery ──→ Normal
   ↑                        │
   └────────────────────────┘ (if recovery impossible → degraded persists)
```

- Entered when the runtime detects instability in S1/S2/S3.
- In degraded mode: no tool calls, no retries, no multi-step reasoning.
- Safe fallback output via `SafeFallbackOutput` schema.

---

## System Alerts

File: `src/platform/supervisor/system_alerts.py`

- **AlertManager** with pluggable transports (Slack, email, collecting).
- `alert_async()` is non-blocking — fires a daemon thread per transport.
- Severity levels: `info`, `warning`, `error`, `critical`.
- All alert delivery wraps in `try/except` — never raises in supervisor loops.

```python
alert_async("critical", "control_plane", "Job poisoned",
            "Job abc-123 exceeded max failure threshold")
```

---

## Related Documents

- [EVENT_SUBSTRATE.md](EVENT_SUBSTRATE.md) — Queue interaction
- [WORKER_POOL.md](WORKER_POOL.md) — Worker lifecycle management
- [LIFECYCLE.md](LIFECYCLE.md) — State machine details
- [BOUNDARIES.md](BOUNDARIES.md) — Import isolation rules
- [OBSERVABILITY.md](OBSERVABILITY.md) — Metrics/trace emission per transition
