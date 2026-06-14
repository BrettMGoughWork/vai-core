# Architecture Overview

Vai-core is organised into six strata (S1–S6), each with a single, bounded responsibility.
Data flows cleanly between layers through well-defined interfaces.

```
External world
     │
     ▼
Channels (S4) ───→ Event Substrate (S4) ───→ S6.0 Trigger Router ───→ S6.2 Workflow Engine
                                                       │                      │
                                                       │                 ┌────┘
                                                       ▼                 ▼
                                                S6.1 Definition ←─ S6.3 Agent Selection
                                                                           │
                                                                           ▼
                                                                     S5 Cognitive Layer
                                                                           │
                                                                           ▼
                                                                     S4 Jobs (execution)

Cron/Timer (S4) ───→ Event Substrate (S4) ───→ S6.0 Trigger Router
```

**Strata summary:**
- **S1** — Foundation: config, LLM transport, types, execution engine, governance, observability, policy, telemetry
- **S2** — Strategy: planning, task decomposition, continuity, state management
- **S3** — Capabilities: primitives, skills, discovery, filtering, ranking
- **S4** — Platform: channels (universal ingress), job system, event substrate, supervision, durability, worker pool
- **S5** — Agents: agent registry, activation, planning loop, job interface, state persistence boundary
- **S6** — Workflow: trigger router, definition model, engine, agent selection, user interaction, supervisor

S4 is the universal ingress for all external stimuli. S6 subscribes to S4 events but owns no
transport. S5 is the only cognitive layer. Each stratum delegates down and notifies up through S4.

---

## Directory Structure

```
config/              # S1 - Runtime configuration files (YAML/JSON/env overrides)
main.py              # S1 - CLI entrypoint (bootstraps config → agent → execution)

src/
  __init__.py

  runtime/           # S1 - Execution engine, retry, recovery, tool wrapper
    pipeline/        # S1 - Pipeline-based execution flow
    recovery/        # S1 - Crash recovery
    retry/           # S1 - Retry policies and poison handling
    safety/          # S1 - Panic guard, degraded mode
    tokens/          # S1 - Token chain management

  strategy/          # S2 - Planning & persistence
    memory/          # S2 - Episodic, working, long-term memory
    planning/        # S2 - Task decomposition, sequencing, plan model

  capabilities/      # S3 - Primitive skills, discovery, ranking
    primitives/      # S3 - Atomic capability implementations
    skills/          # S3 - Markdown skill instruction sets
    registry/        # S3 - Skill registration and discovery

  platform/          # S4 - Execution & runtime platform
    adapter/         # S4 - External service adapters
    config/          # S4 - Configuration system (S4Config, env vars, overrides)
    daemon/          # S4 - Daemon process (instruction dispatch)
    deployment/      # S4 - Local + container deployment targets
    observability/   # S4 - Structured logging, metrics, tracing, health
    queue/           # S4 - Event substrate (in-memory, Redis-backed)
    runtime/         # S4 - Channel registry, control plane, heartbeat, job store, worker pool
    security/        # S4 - Authentication, rate limiting, input validation, sandbox
    supervisor/      # S4 - Worker supervision, control plane, system alerts
    telemetry/       # S4 - Telemetry collection
    transport/       # S4 - HTTP transport layer, normalization
    util/            # S4 - Shared platform utilities

  agents/            # S5 - Agent registry, activation, planning loop (placeholder)
  workflow/          # S6 - Workflow trigger router, engine, definition model (placeholder)
  release/           # S4 - Release checklist and sign-off procedures

tests/
  unit/              # Isolated unit tests (fast, no external deps)
  integration/       # End-to-end and cross-module tests

tools/
  code_analysers/    # CI-enforced architectural invariant checkers
    shared/          # Shared analyser utilities
    stratum1/        # S1 invariant enforcement
    planning/        # S2→S3 boundary adapters
  testing_harness/   # S4 MVP integration test harness
```

---

## Design Principles

- **Separation of concerns**: Each stratum has a single, bounded responsibility.
- **Extensibility**: Channels, skills, and providers plug in without modifying core logic.
- **Observability-first**: All major flows are traceable via structured logs, metrics, and traces.
- **Deterministic by default**: The system produces identical outputs given identical inputs.
- **Fail-fast**: Invalid configuration, malformed inputs, and invariant violations fail immediately.
- **No silent fallback**: Every code path either succeeds or fails explicitly.

---

## Key Architectural Properties

| Property | Guarantee |
|---|---|
| **Import acyclicity** | No circular imports between strata |
| **Purity** | S2 (cognition) is a pure function — no I/O, no side effects |
| **Determinism** | Same inputs → same outputs across all components |
| **Immutable config** | Config is frozen after load; no runtime mutation |
| **Panic safety** | Worker panics are caught, classified, and supervised |
| **Poison isolation** | Poison jobs are quarantined — they cannot destabilise the system |
| **Backpressure** | Channels and queues apply backpressure under load |
| **Idempotency** | Retried operations are safe to replay |

---

## Strata Contracts

### S1 → S2 Boundary (Cognitive Contract)

Defined in detail in `docs/contracts/s2_s3_boundary_v1.0.md`.

Stratum 2 must behave as a pure function:

```
PureInput → PureCognition → PureOutput
```

- S2 receives: `StepState`, `StepResult`, `MemorySnapshot`
- S2 returns exactly one of: `classification`, `subgoal`, `segment`, `plan`, `structured_error`
- S2 must not: call tools, mutate memory, perform I/O, depend on environment

### S2 → S3 Boundary

S3 provides capabilities discovered by S2:
- S2 proposes intent → S3 resolves to available skills
- S3 returns ranked capability list → S2 selects which to invoke

### S3 → S4 Boundary

S4 executes what S3 selects:
- S3 submits a job request → S4 queues and executes it
- S4 returns execution result → S3 feeds back to S2

### S4 → S5/S6 Boundary

S4 is the universal ingress. S5/S6 never own transport:
- S5/S6 subscribe to S4 event substrate
- S5/S6 never listen on ports or own channels
- S4 delivers events; S5/S6 interpret them

---

## Related Documents

| Document | Description |
|---|---|
| [BOUNDARIES.md](BOUNDARIES.md) | Formal boundaries and invariants per stratum |
| [EVENT_SUBSTRATE.md](EVENT_SUBSTRATE.md) | Event substrate architecture and guarantees |
| [CONTROL_PLANE.md](CONTROL_PLANE.md) | Control plane responsibilities and state model |
| [WORKER_POOL.md](WORKER_POOL.md) | Worker pool architecture and concurrency model |
| [LIFECYCLE.md](LIFECYCLE.md) | Lifecycle state machines for all components |
| [CHANNELS.md](CHANNELS.md) | Channel model and pluggable transports |
| [OBSERVABILITY.md](OBSERVABILITY.md) | Logging, metrics, tracing, and health checks |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Local and container deployment targets |
| [ROADMAP.md](ROADMAP.md) | Current roadmap and future phases |

---

## Cognitive Contract (S1 ↔ S2 Interface)

For the full contract specification, see `docs/contracts/s2_s3_boundary_v1.0.md`.

**Summary:**

Stratum 2 is a pure cognitive engine. It receives StepState, StepResult, and MemorySnapshot. It returns exactly one of: classification, subgoal, segment, plan, or structured error. It must not execute tools, mutate memory, perform side effects, or depend on environment state. It must be pure, deterministic, and replayable.