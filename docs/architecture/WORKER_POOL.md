# Worker Pool — Deterministic Concurrency

**Purpose:** Thread-based worker pool with configurable concurrency, clean
shutdown, and stateless handler dispatch.

File: `src/platform/runtime/worker_pool/pool.py`

---

## Architecture Overview

```
                      WorkerPool
        ┌───────────────┼───────────────┐
        │               │               │
    WorkerThread-0  WorkerThread-1  WorkerThread-N
        │               │               │
        └───────────────┼───────────────┘
                        │
                  SupervisorLoop (optional)
                        │
                   evaluate()
                        │
                   apply_decision()
```

- All workers share a `threading.Event` for shutdown signalling.
- The handler _must_ be stateless and idempotent.
- Supervisor is optional; if configured, runs on a fixed interval.

---

## Concurrency Model

| Parameter | Default | Description |
|-----------|---------|-------------|
| `worker_concurrency` | 1 | Number of daemon worker threads |
| `worker_tick_interval` | 0.05s | Sleep gap between handler invocations |
| `supervisor_check_interval` | 5.0s | Seconds between supervisor evaluation cycles |

Workers are `Thread(daemon=True)` — they do not prevent process exit.

```python
pool = create_worker_pool(WorkerPoolConfig(
    worker_concurrency=4,
    worker_handler=process_next_job,
    supervisor_config=SupervisorConfig(timeout_seconds=30),
))
pool.start()
pool.stop()
pool.join()
```

---

## Worker Lifecycle

```
 created ──→ idle ──→ busy ──→ draining ──→ terminated
               │                    ↑
               └────────────────────┘
                    (restart)
```

- **idle:** Worker is alive, no active job, calling handler with no-op.
- **busy:** Worker is processing a job (handler returned normally).
- **draining:** Stop event set, worker finishing current tick then exits.
- **terminated:** Thread has exited.

---

## Heartbeat Model

### Emitter → ControlPlane → Events

```
HeartbeatEmitter (per worker)
    │  emit(active_job_id, cycles_completed, health)
    ▼
ControlPlane.accept_heartbeat()
    │  HeartbeatMonitor.update(event)
    ▼
HeartbeatStatus { worker_id, last_seen, is_healthy, reason }
    │
    ▼
SupervisorLoop.evaluate()
    │  collect_heartbeat() per cycle
    ▼
WorkerRestart decisions
```

The `HeartbeatEmitter` is pure logic — it constructs `HeartbeatEvent` from
provided inputs. `HeartbeatMonitor` is deterministic: same events + same clock
→ same status.

---

## Restart Semantics (Crash Recovery)

1. Worker thread crashes (unhandled exception).
2. `CrashRecoveryStage` catches it and wraps as `PanicDecision`.
3. Pipeline routes the decision back to the control plane.
4. Job is marked `failed` or `poison`.
5. Supervisor detects missing heartbeat on next cycle.
6. Supervisor applies restart decision — old worker is removed, new one created.

The supervisor does **not** kill OS threads directly. It logs restart decisions
via notification; the runtime layer manages thread replacement.

---

## Sandboxing

| Mechanism | Implementation |
|-----------|---------------|
| **Time-bounded execution** | Job timeout enforced by pipeline stages. Worker tick is not time-bounded (responsibility of the handler). |
| **Resource limits** | Not implemented at thread level. Handlers are expected to be well-behaved. |
| **Crash isolation** | `PanicGuard.wrap()` catches all exceptions into `StructuredFailure`. A crash in one worker cannot affect others. |
| **Poison detection** | Jobs exceeding `max_consecutive_failures` are marked `poison` and never retried. |

---

## Execution Envelopes

The worker pipeline wraps each job in a composable execution envelope:

```
CrashRecoveryStage → IdempotencyStage → DegradedModeStage → ExecutionStage
```

| Stage | Responsibility |
|-------|---------------|
| `CrashRecoveryStage` | Catch all exceptions, produce `PanicDecision` |
| `IdempotencyStage` | Ensure job is not already completed |
| `DegradedModeStage` | Short-circuit to safe fallback if degraded |
| `ExecutionStage` | Execute S2→S1→back→S2 adapter chain |

---

## Performance Characteristics

- **Overhead per tick:** ~1ms (thread sleep + handler call + sleep).
- **Context switching:** OS-managed via daemon threads.
- **Scaling:** Worker count is static (configurable at startup). No dynamic
  scaling. No work-stealing between workers.
- **Throughput:** Approximately N\*T where N = workers and T = throughput per
  worker (dominated by handler latency).

---

## Related Documents

- [CONTROL_PLANE.md](CONTROL_PLANE.md) — Heartbeat monitoring and supervision
- [EVENT_SUBSTRATE.md](EVENT_SUBSTRATE.md) — Queue pop semantics
- [LIFECYCLE.md](LIFECYCLE.md) — Worker state machine
- [BOUNDARIES.md](BOUNDARIES.md) — Panic isolation boundaries
