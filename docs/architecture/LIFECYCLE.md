# Lifecycle — State Machines

**Purpose:** Define all state machines in the vai-core runtime, their
transitions, invariants, and recovery paths.

---

## 1. Job Lifecycle

File: `src/platform/runtime/job_state.py`

```
                  ┌─────────────┐
                  │   PENDING   │
                  └──────┬──────┘
                         │ register_job()
                         ▼
                  ┌─────────────┐
    ┌─────────────│   RUNNING   │
    │             └──┬──┬──┬────┘
    │                │  │  │
    │                │  │  └────────────────────┐
    │                │  │                       │
    ▼                ▼  ▼                       ▼
┌───────┐      ┌────────┐              ┌───────────┐
│RETRY  │      │SUCCEED │              │  FAILED   │
│→PENDING│     │ED      │              └─────┬─────┘
└───────┘      └────────┘                    │ max failures exceeded
                                        ┌────▼────┐
                                        │ POISON  │ (terminal)
                                        └─────────┘
```

### Transitions

| From | To | Trigger |
|------|----|---------|
| PENDING | RUNNING | Worker pops job from queue |
| RUNNING | SUCCEEDED | Handler completes without error |
| RUNNING | FAILED | Handler returns error |
| RUNNING | POISON | Consecutive failures > threshold |
| FAILED | PENDING | Retry (requeue) |

### Invariants

- No outgoing transitions from `SUCCEEDED`, `FAILED`, or `POISON`.
- `POISON` is permanent — the job is dead-lettered.
- State validation is O(1) via set lookup.
- Transitions emit metrics and traces via the observability layer.

---

## 2. Worker Lifecycle

File: `src/platform/runtime/worker_pool/pool.py`

```
 ┌──────────┐     start()     ┌──────────┐     handler()    ┌──────────┐
 │ CREATED  │ ──────────────→ │  IDLE    │ ───────────────→ │  BUSY    │
 │ (thread  │                 │ (alive,  │                  │ (processing)
 │  exists) │                 │  no job) │                  │
 └──────────┘                 └──────────┘                  └────┬─────┘
                                 │      ▲                        │
                                 │      │ handler returns         │ handler returns
                                 │      └────────────────────────┘ error → crash
                                 │                                          │
                                 │ stop_event.set()                         ▼
                                 ▼                                   ┌──────────┐
                           ┌──────────┐     join()     ┌──────────┐ │  CRASH   │
                           │ DRAINING │ ──────────────→ │TERMINATED│ │(recovery)│
                           │ (last    │                 │          │ └──────────┘
                           │  tick)   │                 └──────────┘
                           └──────────┘
```

### Heartbeat Timing

| State | Heartbeat `health` |
|-------|-------------------|
| IDLE | `"idle"` |
| BUSY | `"busy"` |
| DRAINING | `"ok"` |
| CRASH | Missing heartbeat → supervisor detects |

### Crash and Restart

1. Worker crashes → heartbeat stops.
2. Supervisor detects missing heartbeat → `is_healthy=False`.
3. Supervisor applies restart decision → `WorkerRestartEvent`.
4. Old worker ID is removed; runtime creates new thread.

---

## 3. Supervisor Lifecycle

File: `src/platform/supervisor/supervisor_loop.py`

```
                    ┌─────────────┐
                    │  RUNNING    │
                    └──────┬──────┘
                           │
                    evaluate() detects issues
                           │
                           ▼
                    ┌─────────────┐
                    │  DEGRADED   │
                    └──────┬──────┘
                           │
                    health restored
                           │
                           ▼
                    ┌─────────────┐
                    │  RECOVERY   │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  RUNNING    │
                    └─────────────┘
```

The supervisor loop cycle:
1. Collect heartbeats from all active workers.
2. Evaluate health (`healthy` / `degraded` / `unresponsive`).
3. Apply restart decisions.
4. Emit structured events and metrics.

---

## 4. Daemon Lifecycle

File: `src/platform/deployment/__init__.py`

```
 STARTING ──→ RUNNING ──→ DRAINING ──→ SHUTDOWN
     │           │            │
     │           │            ├── SIGTERM (container)
     │           │            ├── SIGINT  (local)
     │           │            └── stop() (programmatic)
     │           │
     │           └── crash → emergency exit
     │
     └── config load error → exit(1)
```

---

## 5. PanicGuard Lifecycle

File: `src/platform/runtime/safety/panic_guard.py`

```
 ARMED ──→ TRIGGERED ──→ CLASSIFIED ──→ QUARANTINED
   │          │               │               │
   │    exception caught     wrap in       job marked
   │    by guard            Structured     poison
   │                        Failure
   │
   └── normal return → no transition
```

PanicGuard is **pure logic** — it never mutates state, never writes to queues,
never modifies job store. It returns a `PanicDecision` which the caller applies.

---

## 6. Degraded Mode Lifecycle

File: `src/platform/runtime/safety/degraded_mode.py`

```
                    ┌─────────────┐
       normal       │   NORMAL    │ ←─────┐
         │          └──────┬──────┘       │
         │                 │              │
         ▼                 ▼              │
    instability      ┌─────────────┐      │
    detected ──────→ │  DEGRADED   │      │ recovery
                     └──────┬──────┘      │
                            │             │
                            ▼             │
                     ┌─────────────┐      │
                     │  RECOVERY   │──────┘
                     └─────────────┘
```

In degraded mode, the worker produces `SafeFallbackOutput`:

```python
SafeFallbackOutput(
    status="degraded",
    reason="S1 pipeline instability detected",
    detail="Crash rate exceeded threshold in last 60s",
    job_id="abc-123",
    fallback_action="noop",
    recovery_hint="Reduce request rate and retry",
)
```

No tool calls, no retries, no multi-step reasoning in degraded mode.

---

## Related Documents

- [CONTROL_PLANE.md](CONTROL_PLANE.md) — State transition authority
- [WORKER_POOL.md](WORKER_POOL.md) — Worker thread lifecycle
- [BOUNDARIES.md](BOUNDARIES.md) — Poison isolation
- [EVENT_SUBSTRATE.md](EVENT_SUBSTRATE.md) — Queue ack/nack lifecycle
