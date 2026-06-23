# vai-core

A lightweight, Python-first LLM agent runtime. It gives LLMs structured jobs — deterministic execution, strict capability boundaries, and durable infrastructure — so you can safely build experimental concepts on top.

This is the baseline. On top of it we're exploring **emergent patterns** (LLM-interpreted capability composition that self-codifies from successful behaviour), **council-based post-mortems** (multi-agent retrospective analysis after failures), and **Bayesian-evolutionary adaptive layers** for self-improvement.

*Note: this project is in early development.*

---

## REPL Test Harness

The canonical way to drive the system during development:

```bash
python -m tools.channels.cli_app --interactive
```

Commands:
- Type a request — dispatched through the agent strategy router
- `/agents` — full list of agents
- `/agent <name>` — switch agents
- `/workflows` — full list of workflows
- `/workflow <id>` — explicitly invoke a workflow
- Ctrl+C to exit

---

## Concepts

vai-core is built around four compositional abstractions:

### Primitives

The smallest unit of work — an atomic tool call with a defined input/output contract. Examples: `gmail_send`, `gmail_search`, `github_create_issue`. Primitives are registered in the capability system (S3), discoverable at runtime, and are the only things that touch the outside world.

### Patterns

A pattern is an **LLM-readable instruction template** that teaches an agent *how* to accomplish a goal by composing primitives. Think of it as a recipe — natural-language guidance, not deterministic code. A pattern lives as a YAML file declaring its name, description, required primitives, and step-by-step instructions.

Patterns act as **capability gateways**: if an agent includes a pattern (e.g., `reply_to_email`), it automatically gains access to that pattern's required primitives (`gmail_read`, `gmail_send`) — even if those primitives aren't explicitly listed in the agent's tool set.

Patterns can also be called as workflow steps via the `apply_pattern` step type, bridging LLM interpretation and deterministic orchestration.

### Workflows

A workflow is a **deterministic directed step graph** — an explicit sequence of operations executed by the workflow engine. Step types include:

| Step | Purpose |
|------|---------|
| `llm_call` | Invoke the LLM with a prompt |
| `tool_execute` | Run a registered primitive |
| `sub_workflow` | Call another workflow (composition) |
| `user_input` | Pause for human input |
| `condition` | Branch on runtime state |
| `apply_pattern` | Invoke a pattern by ID within the workflow |
| `todo_execute` | Execute a todo-list item via the planner worker |

Workflows are engine-driven: the runtime owns the state machine, persists instance state at every mutation, and guarantees exactly-once step transitions. They're ideal for repeatable, auditable processes.

### Agents

An agent is a **persona plus a capability set** — it has a system prompt (persona), and declares which tools, patterns, and workflows it can use. When a user sends a message, the strategy router selects the best agent for the intent, injects the agent's persona and capabilities into the LLM context, and hands off execution.

Agents can also select and invoke workflows as tools — the agent decides which workflow fits the user's intent, and the workflow engine takes over from there.

#### Agent Deferral

An agent can optionally declare a list of peer agents it can **defer** to — handing off work mid-conversation when another agent is better suited. The delegating agent suspends, the delegate runs with its own persona and tools, and control returns to the delegator with the delegate's response injected as context.

This enables **specialisation** (a general support agent hands off billing queries to a billing specialist), **capability mismatch** (a chat assistant defers execution to a task-specific agent), and **task decomposition** (one agent breaks a complex request into sub-tasks for peers). The deferral graph is validated for acyclicity at registration time — no agent can defer, directly or indirectly, back to itself.

See [Agent Deferral](docs/architecture/agent-deferral.md) for the full design.

#### Sub-Goal Planner (Two-Level Planning)

The **sub-goal planner** is a two-level planning architecture that decomposes complex requests into *sub-goals* (coarse milestones) and then iteratively breaks each sub-goal into *tasks* (concrete actions). It is a **first-class capability** — automatically invoked by the S5 Supervisor when the LLM creates goals, not a tool the LLM calls directly.

**How it works (end-to-end):**

```
User Request
    │
    ▼
┌─ S5 Supervisor ──────────────────────────────────────────┐
│  1. LLM creates sub-goals via stdlib.todo.create_batch    │
│  2. ToolOrchestrator executes the primitive inline        │
│  3. Supervisor detects create_* call → auto-invokes       │
│     TodoOrchestrator.run(db_path)                         │
└──────────────────────────────────┬───────────────────────┘
                                   │
                                   ▼
┌─ TodoOrchestrator (S4 Job) ──────────────────────────────┐
│  For each sub-goal (respecting dependencies):             │
│                                                           │
│  ┌─ Inner Loop (Two-Level) ───────────────────────────┐  │
│  │  anchor → reflect → create task → execute → assess │  │
│  │  Loop until sub-goal criterion met (max 10 iter)   │  │
│  └────────────────────────────────────────────────────┘  │
│                                                           │
│  ✓ Sub-goal 1 complete → advance to Sub-goal 2            │
│  ✓ Sub-goal 2 complete → advance to Sub-goal 3            │
│  ...                                                      │
└───────────────────────────────────────────────────────────┘
```

**Core components:**

| Component | Role |
|-----------|------|
| `TodoStore` | SQLite table CRUD with dependency resolution, goal/task type distinction, parent-goal scoping, and progress compaction |
| `TodoWorker` | S4-compatible worker — dispatches `subgoal-execute-loop` for goals vs `todo-execute-item` for tasks. Crash recovery and idempotency built in |
| `TodoOrchestrator` | First-class capability — `run(db_path)` creates a job, enqueues it, runs the full S4 pipeline, and returns results |
| `stdlib.todo.create_batch` | Primary entry point — the LLM calls this primitive to create sub-goals; the Supervisor auto-detects this and invokes the orchestrator |
| `stdlib.todo.create_goal` | Single-goal variant — create one sub-goal at a time |

**Workflows:**

| Workflow | Purpose |
|----------|---------|
| `subgoal-execute-loop` | Two-level inner loop for one sub-goal: anchor → adviser-reflect → create task → execute → assess → repeat until done |
| `todo-execute-item` | Single-task execution with parent-goal context anchoring |
| `todo-self-check` | Gate: verify sub-goal output meets the completion criterion before marking `done` |

**Guardrails:**

| Risk | Mitigation |
|------|------------|
| Infinite inner loop | Hard cap: `max_iterations_per_goal` (default 10) — sub-goal marked `failed` if exceeded |
| Hallucinated completion | Dual gate: adviser must cite evidence + `todo-self-check` verifies criterion |
| Context window bloat | Progress compaction: task outcomes summarized into the sub-goal's description, not raw conversation |
| Task drift | Triple-anchored: adviser prompt, task creation prompt, and task execution prompt all include the parent sub-goal context |
| Over-decomposition | Adviser guidance: "suggest the single most impactful next task — a meaningful unit of work, not every micro-step" |
| Dependency deadlock | Same dependency resolution as the flat planner, scoped within each sub-goal |

---

## Compositional Philosophy

```
Primitives  →  atomic execution, one function call
Patterns    →  instructional composition, LLM-interpreted
Workflows   →  deterministic orchestration, engine-driven
Agents      →  persona + capabilities, the cognitive actor
```

Each layer builds on the one below it. Patterns compose primitives. Workflows can invoke patterns. Agents wield all three through their capability declarations. The system is designed so that **you choose the right abstraction for the job** — a deterministic workflow for repeatable pipelines, a pattern for fuzzy human-like tasks, a raw primitive when you just need one thing done.

Nothing is hidden. Capabilities are explicitly declared in YAML. Every invocation is traced. Every state transition is persisted.

---

## Runtime Infrastructure

The platform layer (S4) provides durable execution:

- **Jobs** — every inbound message is wrapped as a `Job` with a UUID, lifecycle state machine, and append-only transition trace. Jobs are the unit of work and the unit of observability.
- **Queues** — FIFO queues with lease semantics and pluggable backends (in-memory, Redis-ready).
- **Workers** — pop jobs from the queue, run them through a composable pipeline (pre-flight checks → multi-cycle execution → crash recovery → degraded mode → evaluator), and return results. Worker pools support isolation and auto-restart.
- **Control Plane** — the authoritative source of job state. Validates all state transitions, maintains the job registry, and monitors worker heartbeats. Paired with a supervisor loop for worker lifecycle management.
- **Resilience** — circuit breakers, retry policies with backoff, poison job detection, and crash recovery built into the worker pipeline.
- **Gateways** — transport-agnostic ingress via channels (CLI, HTTP, WebSocket, webhook) with provider adapters for Slack, GitHub, Jira, and WhatsApp. All inbound events are normalised to a canonical `ChannelMessage`.

---

## Documentation

- [Architecture](docs/architecture/ARCHITECTURE.md) — strata, boundaries, data flow
- [Roadmap](docs/architecture/ROADMAP.md) — sprint-based planning, Y-horizon experimental features
- [Contracts](docs/contracts/) — interface boundaries between strata
- [Lifecycle](docs/architecture/LIFECYCLE.md) — boot sequence, shutdown, state management
- [Observability](docs/architecture/OBSERVABILITY.md) — metrics, tracing, dashboards
- [Worker Pool](docs/architecture/WORKER_POOL.md) — worker lifecycle, isolation, pipeline
- [Channels](docs/architecture/CHANNELS.md) — transport abstraction, provider adapters
