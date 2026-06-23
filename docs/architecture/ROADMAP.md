# Roadmap v2 — Sprint-Based Planning

> **Status:** Living document  
> **Last updated:** 2026-06-21 (Sprint 17 — added, Sprint 8 env-var fix)  
> **Previous:** `ROADMAP.md` (stratum-based, superseded)  
> **Architecture reference:** [docs/architecture/ARCHITECTURE.md](./ARCHITECTURE.md)

---

## Architecture Overview

```
External world
    │
    ▼
Channels (S4 — universal ingress)
  CLI · HTTP · WebSocket · Webhook · Discord · Slack · SMTP
    │
    ▼
Event substrate (S4 — queueing, durability, supervision)
    │
    ├──────────────────────────────────────────────┐
    ▼                                              │
S6.0 — Workflow Trigger Router                    │
    │  Filters workflow-relevant events            │
    ▼                                              │
S6.2 — Workflow Engine (state machine)            │
    │  llm_call → S1 | tool_execute → S4/S3       │
    │  planner_call → S2 | sub_workflow → S6      │
    │  user_input → Human | condition → branch    │
    │                                              │
    ▼                                              │
S5 — Agent Runtime                                 │
    │  Persona · Strategy Router · Gateway Adapter │
    │  Routes: S1 (LLM), S2 (planner), S3 (skills)│
    │  Agent selects workflows as tools            │
    │                                              │
    ├──────────┬──────────┬──────────┬─────────┐    │
    ▼          ▼          ▼          ▼         ▼    │
S1 Runtime  S2 Planner  S3 Capab.  S4 Platform     │
  (LLM)     (pure)     (tools,      (durable exec) │
                       patterns,                    │
                       workflows)                   │
                                   ─────────────────┘
```

### Key Principles

- **S4** is the universal ingress — transport, normalization, queueing, durability, supervision
- **S5** owns agent persona, strategy routing, and agent-to-workflow selection
- **S6** owns workflow definitions, state machine execution, and trigger routing
- **S6 does not own transport** — it subscribes to S4's event substrate

### Trigger Sources for S6

| Source | Path | Example |
|--------|------|---------|
| A. User-initiated | User → Channel (S4) → S4 ingress → S6 Trigger Router → Engine | Chat message invoking `/workflow report` |
| B. System-initiated | Cron/timer → S4 event substrate → S6 Trigger Router → Engine | Weekly report generation |
| C. Workflow-internal | Step completes → Engine schedules next step | "X is done, now do Y" |
| D. Agent-selected | S5 agent selects workflow as a tool during LLM call | "I need to run a report, this workflow does that" |
| E. Workflow composition | Parent workflow → S6 → child workflow | Sub-workflow call with input/output merge |

### Agent-Workflow Interaction Model

- **Workflows are templates** — declarative YAML files defining step graphs
- **Agents are execution contexts** — they carry persona, state, and routing logic
- **1:N relationship** — one agent can invoke any workflow; one workflow can be run by any agent
- **Agent selection** — different agents can handle different workflow steps (agent_profile field)
- **Workflow discovery** — agents can discover and select workflows as tools ("I can do that via workflow X")
- **Future: Agent-authored workflows** — agents create/repair YAML workflow files for emergent, repeatable behavior

---

## ✅ Completed Sprints (Shipped)

### Sprint 1 — Foundation (S1–S4)

**Goal:** Core execution infrastructure — LLM transport, planning, capabilities, platform runtime.

| Component | What | Status |
|-----------|------|--------|
| S1 Runtime | LLM transport, provider abstraction (OpenAI, DeepSeek, etc.), config-driven model selection | ✅ |
| S2 Planner | AgentPlanner, SubgoalPlanner, MemoryGovernance, goal decomposition → subgoals → segments | ✅ |
| S3 Capabilities | SkillRunner, SkillRegistry, fetch/execute tools, patterns (instructional composition) | ✅ |
| S4 Platform | Queue, Worker, JobStore, supervision, retry, durability (in-memory) | ✅ |

### Sprint 2 — Agent Runtime (S5)

**Goal:** Agent execution loop with strategy routing, persona, and Gateway adapter.

| Component | What | Status |
|-----------|------|--------|
| S5 Supervisor | Agent activation, step execution loop, workflow dispatch | ✅ |
| Strategy Router | Routes llm_call → S1, planner_call → S2, tool_call → S3/S4 | ✅ |
| Gateway Adapter | AgentGatewayAdapter — `ingest()` → S5 processing → response | ✅ |
| Composition Root | Dependency injection wiring for all strata | ✅ |

### Sprint 3 — Workflow YAML + Engine (S6.1 + S6.2)

**Goal:** Declarative YAML workflows with full state machine execution.

| Component | What | Status |
|-----------|------|--------|
| Workflow Definition Model | Pydantic models for workflows, steps, transitions | ✅ |
| YAML Loader | Scans `config/workflows/*.yaml`, validates via Pydantic | ✅ |
| Workflow Registry | In-memory, registered in composition_root | ✅ |
| Workflow Engine | State machine — 6 step types, shared context, template rendering | ✅ |
| Step Handlers | llm_call, tool_execute, sub_workflow, user_input, condition, planner_call | ✅ |
| Inline Tool Executor | Bypasses S4 for synchronous tool execution | ✅ |
| Template Rendering | `{context.X}`, `{result.X}` in step config | ✅ |
| CLI Gateway → S5 → S6 | `python -m tools.channels.cli_app "/workflow <name>"` | ✅ |

**Workflows in config/workflows/:**
- `default-agent.yaml` — single LLM call
- `tools-workflow.yaml` — tool execute via inline executor
- `waiting-agent.yaml` — user_input + LLM chain
- `multi-step.yaml` — two-step LLM analysis
- `planner-demo.yaml` — planner_call + tool_execute

### Sprint 4 — Planner Call Step

**Goal:** Wire the planner_call step type end-to-end so a YAML workflow can decompose a goal via S2 Planner, create subgoals/segments in memory, and execute the resulting steps.

**Epic tracking:** Planner call → S2 → plan → subgoals/segments → step execution

| Task | What | Status |
|------|------|--------|
| 4.1 | Add `planner_call` step handler to Engine | ✅ Done |
| 4.2 | Handle `planner_call` outcome in Supervisor | ✅ Done |
| 4.3 | Wire planner + capability_discoverer in composition_root | ✅ Done |
| 4.4 | Fix `_WiredPlanner.plan()` fallback field names | ✅ Done |
| 4.5 | Create `planner-demo.yaml` workflow | ✅ Done |
| 4.6 | Step execution wiring — plan steps → inline executor | ✅ Done |
| 4.7 | Goals/subgoals/segments creation in MemoryGovernance | ✅ Done |
| 4.8 | Test: full planner_call → tool_execute → completion via CLI | ✅ Done |
| 4.9 | Test: drift detection, confidence scoring | ✅ Done |

### Sprint 4a — Multi-Turn Conversation Memory

**Goal:** Enable multi-turn conversation memory in the interactive CLI so each prompt can reference prior exchanges in the same session.

| Task | What | Status |
|------|------|--------|
| 4a.1 | Add `conversation_history` field to `AgentState` dataclass | ✅ Done |
| 4a.2 | Accumulate conversation history across turns in the CLI loop (`tools/agent/cli_app.py`) | ✅ Done |
| 4a.3 | Wire accumulated history into `PromptRequest` via S5 → StrategyRouter → S1 | ✅ Done |
| 4a.4 | Update S1 conversational backend to render prior turns in the system prompt | ✅ Done |
| 4a.5 | Wire `MemoryGovernance` into the `DEST_RUNTIME` path in `strategy_router.py` | ✅ Done |
| 4a.6 | Pass governance context into `PromptRequest.memory` | ✅ Done |
| 4a.7 | Integration test: multi-turn conversation references prior content | ✅ Done |
| 4a.8 | Integration test: fresh session boundary isolates history | ✅ Done |
| 4a.9 | Test: drift events emitted for conversational turns | ✅ Done |

### ✅ Sprint 5 — End-to-End Wiring & Integration Tests

**Goal:** Wire the full Gateway → S5 → S6 → S1/S2/S3 pipeline so a single message exercises all layers.

| Task | What | Status |
|------|------|--------|
| 5.1 | In-memory S4 job queue + test workflow fixture | ✅ Done |
| 5.2 | Wire FastAPI app with real Supervisor, WorkflowRegistry, submit_job_callable | ✅ Done |
| 5.3 | Integration test: Gateway → S5 → workflow → LLM call → complete | ✅ Done |
| 5.4 | Integration test: workflow tool_execute → S4 jobs → waiting/resume | ✅ Done |
| 5.5 | Integration test: full workflow with multiple step types | ✅ Done |
| 5.6 | CI step: run integration tests on every PR | ✅ Done |

---

## 🏃 Current Sprint

### Sprint 6 — Trigger Router

**Goal:** S6 subscribes to S4's event substrate, filters workflow-relevant events, and routes to the workflow engine.

**Files to create:**
- `src/agent/workflow/trigger_router.py` — TriggerRouter, WorkflowEvent
- `src/agent/workflow/event_bus.py` — lightweight in-process event bus (stand-in for S4b)

| Task | What | Status |
|------|------|--------|
| 6.1 | Define WorkflowEvent dataclass (event_type, payload, correlation_id, timestamp) | ✅ |
| 6.2 | Implement TriggerRouter.handle_event() — find matching workflows, start instances | ✅ |
| 6.3 | Implement lightweight EventBus with subscribe/publish | ✅ |
| 6.4 | Wire trigger router to event bus | ✅ |
| 6.5 | Test: matching event → workflow instance created | ✅ |
| 6.6 | Test: non-matching event → no instance | ✅ |
| 6.7 | Test: resume event for paused workflow → engine.resume() | ✅ |

**Events S6 subscribes to:**
- `workflow.start`
- `workflow.resume`
- `workflow.timeout`
- `workflow.external_input`
- `workflow.scheduled_trigger`

### Sprint 7 — Workflow Supervisor / WorkflowOps ✅

**Goal:** Operational visibility and management for all running workflow instances — list, inspect, cancel, retry, dead-letter queue, metrics.

| Task | What | Status |
|------|------|--------|
| 7.1 | WorkflowInstanceStore — save, get, list (by workflow_id, status), delete | ✅ |
| 7.2 | WorkflowOps — list_instances, get_instance, cancel, retry | ✅ |
| 7.3 | WorkflowOps — dead_letter_queue, metrics | ✅ |
| 7.4 | Wire store updates into Supervisor (write-through on each state transition) | ✅ |
| 7.5 | Test: cancel running/paused workflow | ✅ |
| 7.6 | Test: retry failed workflow → preserves context | ✅ |
| 7.7 | Test: metrics returns correct counts | ✅ |

### Sprint 8 — User Interaction Layer ✅

**Goal:** Workflows pause for human input with validation, timeout, and resume.

**Files created:**
- `src/agent/workflow/user_interaction.py` — UserInteractionManager, InteractionRequest, InteractionResponse

| Task | What | Status |
|------|------|--------|
| 8.1 | InteractionRequest/Response dataclasses with input_schema | ✅ |
| 8.2 | UserInteractionManager — request_input, submit_response | ✅ |
| 8.3 | Validate input against schema (type checks, required fields) | ✅ |
| 8.4 | Timeout handling — engine transitions to timeout state | ✅ |
| 8.5 | Integration: CLI displays prompts, collects responses | ✅ |
| 8.6 | Test: valid input → resume → workflow continues | ✅ |
| 8.7 | Test: invalid input → returns False, engine not called | ✅ |
| 8.8 | Test: timeout → engine transitions correctly | ✅ |

### Sprint 9 — Agent Selection Layer ✅

**Goal:** Match workflow steps to agent personas. When a workflow step needs an agent (for `user_input` or delegated `llm_call`), determine which agent/persona handles it.

| Task | What |
|------|------|
| 9.1 | Define agent_profile field in workflow step config | ✅ |
| 9.2 | Agent registry — list available agents with capabilities/persona | ✅ |
| 9.3 | Agent selection strategy — profile match, round-robin, explicit | ✅ |
| 9.4 | Wire selection into Supervisor when stepping workflow | ✅ |
| 9.5 | Test: explicit agent_profile → correct agent selected | ✅ |
| 9.6 | Test: no agent_profile → runtime agent used | ✅ |
| 9.7 | Test: agent not found → configurable fallback/fail | ✅ |

### Sprint 9a — Workflow Discovery for Agents ✅

**Goal:** Agents discover and select workflows as tools during LLM calls — the S5 agent sees registered workflows alongside skills and can invoke them via tool-call routing.

**Files to create:**
- `src/agent/workflow/workflow_tool_adapter.py` — WorkflowToolAdapter

| Task | What |
|------|------|
| 9a.1 | WorkflowToolAdapter — converts WorkflowRegistry entries into LLM tool definitions (name, description, input_schema from YAML) | ✅ |
| 9a.2 | Wire adapter into S5 Supervisor's tool registry — workflows appear alongside skills as callable tools | ✅ |
| 9a.3 | Handle workflow tool call in Supervisor — route `workflow.execute` calls to WorkflowEngine instead of SkillRunner | ✅ |
| 9a.4 | Parameter passthrough — LLM tool call params → workflow input state | ✅ |
| 9a.5 | Test: agent invokes workflow via tool call → workflow starts and completes | ✅ |
| 9a.6 | Test: workflow tool call with params → correctly populates initial state | ✅ |
| 9a.7 | Test: agent calls non-existent workflow → graceful error (tool not found) | ✅ |
| 9a.8 | Test: workflow tool appears/disappears based on registration state | ✅ |

### Sprint P1 — Patterns: Definition & Registry

**Goal:** Introduce "patterns" as a first-class S3 capability type — instructional, LLM-readable templates that teach agents *how* to compose primitives to achieve goals (e.g. `reply_to_email`, `triage_inbox`). Patterns sit between tools (atomic execution) and workflows (deterministic step graphs) on the capability spectrum.

**Files to create:**
- `src/capabilities/patterns/__init__.py`
- `src/capabilities/patterns/pattern_schema.py` — Pydantic `PatternDefinition` model
- `src/capabilities/patterns/pattern_loader.py` — YAML loader for `config/patterns/*.yaml`
- `src/capabilities/patterns/pattern_registry.py` — in-memory registry
- `config/patterns/` — example patterns (reply-to-email, summarise-inbox, triage-inbox)

| Task | What |
|------|------|
| P1.1 | Define `PatternDefinition` Pydantic model — pattern_id, name, description, primitives (required tools), instructions (natural-language guidance), examples, version |
| P1.2 | Create YAML loader — scan `config/patterns/*.yaml`, validate via Pydantic |
| P1.3 | Build `PatternRegistry` — in-memory, registered in `composition_root`, discoverable via S3 capability discovery |
| P1.4 | Wire pattern registry into S3's `capability_discoverer` — patterns appear alongside primitives in discovery results |
| P1.5 | Create example patterns: `reply_to_email` (gmail_read → compose → gmail_send), `summarise_inbox` (gmail_search → read → summarise), `triage_inbox` (gmail_search → categorize → flag) |

### Sprint P2 — Patterns: Agent Integration

**Goal:** Agents declare patterns as capabilities. Pattern instructions are injected into the LLM context. An agent that knows pattern-X gets its instructions even if the agent doesn't list the underlying primitives directly — the pattern acts as a capability gateway.

**Files to modify:**
- `src/agent/registry.py` — add `patterns: List[str]` to `AgentMetadata`
- `src/agent/loaders/yaml_loader.py` — parse `patterns:` from agent YAML
- `src/agent/tool_orchestrator.py` — inject pattern instructions into tool_context
- `config/agents/` — add `patterns:` to relevant agent configs

| Task | What |
|------|------|
| P2.1 | Add `patterns: List[str]` to `AgentMetadata` dataclass |
| P2.2 | Update YAML agent loader to parse `patterns:` field from agent config |
| P2.3 | Pattern-primitive resolution — when building tool context for an LLM call, resolve each agent pattern → its required primitives, include even if agent doesn't list them directly |
| P2.4 | Inject pattern instructions into LLM tool_context — patterns appear as instructional context (not tool definitions) so the LLM can follow their guidance |
| P2.5 | Test: agent with pattern but not underlying tool → LLM can still follow pattern instructions and call tools resolved by the pattern |
| P2.6 | Test: pattern discovery — agents can discover available patterns via S3 capability discovery |

### Sprint P3 — Patterns: Workflow & Learning Integration (Future)

**Goal:** Make `apply_pattern` a first-class workflow step. Enable agents to author patterns (Y.8 Learning Subsystem).

| Task | What |
|------|------|
| P3.1 | `apply_pattern` workflow step type — injects pattern instructions into an LLM call context within a workflow |
| P3.2 | Pattern call as first-class step in workflow engine — `workflow_step.type == "apply_pattern"` |
| P3.3 | Agent-authored patterns — agents create/repair pattern YAML files (per Y.8 Learning Subsystem) |
| P3.4 | Pattern lifecycle — candidate → draft → published → deprecated (HITL approval gate) |
| P3.5 | Pattern composition — can patterns reference other patterns? (keep out of scope initially) |

### Sprint D1 — Agent Deferral

**Goal:** Agents can declare a list of peer agents they are allowed to defer/hand-off work to. A delegating agent suspends, the delegate runs with its own persona and tools, and the delegating agent resumes with the delegate's response. The deferral graph must be acyclic — enforced at registration time.

**Concept doc:** [docs/architecture/agent-deferral.md](./agent-deferral.md)

**Files to create/modify:**
- `src/agent/deferral/` — resolver, context bridge, depth guard
- `src/agent/registry.py` — add `defer_to: List[str]` to `AgentMetadata`, acyclicity validator
- `src/agent/supervisor.py` — `defer_to_agent()` method, suspend → delegate → resume flow
- `src/agent/loaders/yaml_loader.py` — parse `defer_to:` from agent YAML
- `src/agent/tool_orchestrator.py` — expose `defer_to` as a tool so LLMs can invoke it
- `tests/unit/agent/deferral/` — cycle detection, hand-off/back, depth limit, context isolation

| Task | What |
|------|------|
| D1.1 | Add `defer_to: List[str]` to `AgentMetadata` — optional list of peer agent IDs |
| D1.2 | Acyclicity validator — walk deferral graph at registration, reject cycles with a clear error message listing the cycle path |
| D1.3 | YAML loader — parse `defer_to:` from agent config files |
| D1.4 | Deferral resolver — given an agent_id + prompt, resolve the delegate agent's metadata, validate it exists and is not the caller |
| D1.5 | Context bridge — package the delegating agent's conversation context into a prompt for the delegate; inject the delegate's response back on resume |
| D1.6 | Supervisor `defer_to_agent(target, prompt)` — suspend current agent, activate delegate, run delegate to completion, resume original with delegate response |
| D1.7 | Depth guard — configurable max deferral chain depth (default: 3) to prevent runaway chains even with acyclic graphs |
| D1.8 | Expose `defer_to` as a tool to the LLM — agent personas can instruct "when you detect a billing query, defer to billing-agent" |
| D1.9 | Test: cycle detection rejects direct mutual deferral (A→B, B→A) |
| D1.10 | Test: cycle detection rejects indirect cycle (A→B→C→A) |
| D1.11 | Test: valid chain (A→B→C) registers without error |
| D1.12 | Test: hand-off → delegate runs → hand-back → original agent sees delegate response |
| D1.13 | Test: depth limit — chain of 4 defers with max_depth=3 raises DeferralDepthError |
| D1.14 | Test: delegate agent runs with its own tools/persona, not the caller's |

**⚠️ Concerns to watch during implementation:**
- **Context blow-up** — each deferral appends the full delegate conversation to the caller's history. Consider summarising the delegate's response before handing back for longer chains.
- **Tool isolation** — the delegate must have the tools it needs. If the delegating agent detects a capability mismatch, deferral is the correct path, but the delegate must actually have those tools.
- **Infinite loops via workflow/pattern** — agent A defers to B, B runs a workflow that invokes agent A. Mitigated by the acyclicity check + depth guard, but workflow-level loops need a separate guard (out of scope for D1).

### Sprint 10 — Refactor: Stratum Isolation

**Goal:** Enforce strict layer boundaries. S1 knows nothing of S2/S3/S4. S2 is pure (no I/O). S4 is generic. S5 is sole orchestrator.

| Task | What |
|------|------|
| 10.1 | Gateway extraction — move transport + channels from S4 to `src/gateway/` |
| 10.2 | S2 purification — remove S1 coupling (inject llm_complete callable) |
| 10.3 | S2 purification — remove S3 coupling (symbolic skill refs only) |
| 10.4 | S4 slimming — generic WorkExecutor, no routing/dispatch logic |
| 10.5 | Move LLM providers `src/strategy/llm/providers/` → `src/runtime/llm/providers/` |
| 10.6 | Define S5→S1/S2/S3/S4 protocol interfaces |
| 10.7 | Route LLM tool_calls from S1 back to S5 → S3 |
| 10.8 | Stratum isolation audit — CI-enforced boundary rules |
| 10.9 | Fix architecture audit: 0 Critical, 0 High |
| 10.10 | Update all docs to reflect refactored boundaries |

### Sprint 11 — Durable Execution: Real S4 Queue

**Goal:** Replace in-memory S4 with a real durable execution queue. Enables crash recovery, retry with backoff, and cross-process workloads.

| Task | What |
|------|------|
| 11.1 | Define S4B queue interface (enqueue, dequeue, ack, nack, requeue) |
| 11.2 | SQLite-backed queue implementation (sufficient for single-node) |
| 11.3 | Retry with exponential backoff + max_retries |
| 11.4 | Dead-letter queue for unrecoverable jobs |
| 11.5 | Job timeout / TTL |
| 11.6 | Wire real queue into S4 worker, replacing InMemoryJobStore |
| 11.7 | Test: crash recovery — jobs requeued on restart |
| 11.8 | Test: retry backoff — increasing delays between retries |
| 11.9 | S4 fan-out — dispatch N independent steps as parallel sub-agents from a single workflow step |
| 11.10 | S4 fan-in — collect results from parallel sub-agents, join on completion or first-failure |
| 11.11 | Per-sub-agent model/agent override — each parallel branch can specify a different agent or LLM model |
| 11.12 | Dependency graph support — express step dependencies (not just flat list) for partial parallelism |
| 11.13 | Test: 3 parallel steps → all complete → join merges results correctly |
| 11.14 | Test: one parallel step fails → fan-in handles partial failure (configurable: abort-all vs continue) |

### Sprint 12 — Real S3 Skill Registry

**Goal:** Beyond the `test_tool` stub — real tool discovery, registration, and execution.

| Task | What |
|------|------|
| 12.1 | Define SkillDefinition model (name, description, parameters, handler) |
| 12.2 | SkillRegistry — register, discover, get |
| 12.3 | Plugin-based skill loading from `tools/skills/` or config |
| 12.4 | Skil discovery API for S5 (capability_discoverer → real data) |
| 12.5 | Skill documentation generation (LLM-readable tool descriptions) |
| 12.6 | Test: register → discover → execute cycle |
| 12.7 | I would like to test both a cli tool registered, and a basic MCP tool registered with both working, discoverable, and callable

### Sprint 12a — Todo-List Planner (replaces SQL Structured Data Skill)

**Goal:** A first-class composite capability that replaces the monolithic S2 hierarchical planner with a flat, SQLite-backed todo list. The list *is* the source of truth — no drift, no separate memory, no rerun machinery. Built from the same composable pieces as the rest of the system: S4 workers for durability, workflows for execution structure, patterns for LLM guidance, and stdlib db primitives for persistence.

**Scope:** This is *not* a skill — it is a composite capability woven from S3, S4, S5. The S4 worker owns the iteration loop; workflows stay acyclic. Once this is stable, a future refactor will unstitch S2 from the system (massive simplification).

**Architecture:**

```
/src/capabilities/planner/           ← orchestration & machinery (NEW)
  __init__.py
  todo_store.py                      ← SQLite wrapper: schema, CRUD, dependency resolution
  todo_worker.py                     ← S4 worker: polls job queue, iterates todos, dispatches, updates
  todo_orchestrator.py               ← Submits todo-list jobs to S4, manages lifecycle

/src/capabilities/primitives/stdlib/
  db_execute.py                      ← NEW: DDL executor (CREATE TABLE, DROP, ALTER, CREATE INDEX)
  db_connect.py / db_query.py / ...  ← Existing: reused as-is

/config/workflows/
  todo-execute-item.yaml             ← NEW: acyclic per-item execution workflow

/config/patterns/
  todo-breakdown.yaml                ← NEW: LLM guidance for decomposing goals into todo items
  todo-prioritize.yaml               ← NEW: LLM guidance for dependency-aware ordering
  todo-self-check.yaml               ← NEW: LLM guidance for verifying completed items
```

**How the loop works (no workflow extension needed):**

```
S5 submits job "execute this todo list" → S4 queue
  └─ TodoWorker picks up job
       ├─ connect to SQLite (stdlib.db.connect)
       ├─ ensure tables exist (stdlib.db.execute)
       ├─ WHILE ready todos remain:
       │    ├─ pick next pending todo (respecting todo_deps)
       │    ├─ mark it in_progress
       │    ├─ run workflow "todo-execute-item" (per-item, acyclic)
       │    ├─ on success → mark done
       │    ├─ on failure → decrement retries or mark failed
       │    └─ continue
       └─ mark job complete
```

The worker leverages existing S4 machinery: `ToolRetryWrapper`, `CrashRecovery`, `PanicGuard`, `DegradedMode`. On crash, it reloads the job, reads current list state from SQLite, and resumes — no replay needed.

**Data model (SQLite):**

```sql
CREATE TABLE todos (
    id TEXT PRIMARY KEY,          -- kebab-case, e.g. "create-auth-module"
    title TEXT NOT NULL,          -- gerund form, e.g. "Creating auth module"
    description TEXT,             -- enough detail to execute without referring back
    status TEXT DEFAULT 'pending', -- pending | in_progress | done | failed | blocked
    retries_remaining INT DEFAULT 3,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE todo_deps (
    todo_id TEXT REFERENCES todos(id),
    depends_on TEXT REFERENCES todos(id),
    PRIMARY KEY (todo_id, depends_on)
);
```

| Task | What |
|------|------|
| 12a.1 | **`stdlib.db.execute` primitive** — DDL executor (CREATE TABLE, DROP, ALTER, CREATE INDEX). Security: DDL only (no DML — INSERT/UPDATE/DELETE use their own primitives). Follows existing `db_connect` context pattern. Tests: creates table, rejects DML, rejects invalid SQL, works with existing connection context. |
| 12a.2 | **`TodoStore`** — SQLite wrapper in `/src/capabilities/planner/todo_store.py`. Creates/manages `todos` and `todo_deps` tables. Provides: `ensure_tables()`, `add_todo(id, title, description)`, `get_next_pending()` (topological — respects deps, picks in_progress items first on resume), `mark_done(id)`, `mark_failed(id)`, `mark_blocked(id, reason)`, `add_dep(todo_id, depends_on)`. Pure data layer — no S4 or agent knowledge. |
| 12a.3 | **`TodoWorker`** — S4-compatible worker in `/src/capabilities/planner/todo_worker.py`. Signature: `WorkExecutor` compatible (receives `(payload, execution_context, resume_token, **kwargs) → dict`). Loop: SQLite connect → ensure tables → while ready todos → pick next → run per-item workflow → update status → repeat. On crash: reloads job from JobStore, reads current todo state, resumes. Respects `retries_remaining` per item. Unit tests with mock workflow/submitter. |
| 12a.4 | **`TodoOrchestrator`** — Job lifecycle manager in `/src/capabilities/planner/todo_orchestrator.py`. `submit_plan(todo_items: list[dict]) → job_id`: creates SQLite DB, populates todos, submits S4 job. `get_status(job_id) → JobState`: polls job status. `get_results(job_id) → list[todo]`: returns final list state. Called by S5 when an agent decides to use the planner. |
| 12a.5 | **Workflow: `todo-execute-item`** — Acyclic per-item execution workflow (`config/workflows/todo-execute-item.yaml`). Steps: `llm_call` (execute the todo description with agent's tools/context) → `condition` (on_success → `tool_execute` mark done via stdlib.db.update; on_failure → mark failed, include error). Has `retry_policy` (max 3 retries with backoff). Sub-workflow of the worker loop. |
| 12a.6 | **Pattern: `todo-breakdown`** — LLM guidance for decomposing a user goal into flat todo items with dependencies. Instructs the agent to: identify independent subtasks, write gerund-form titles, include enough description detail per item, express dependencies via `depends_on`, estimate ordering. Registered in `config/patterns/todo-breakdown.yaml`. |
| 12a.7 | **Pattern: `todo-prioritize`** — LLM guidance for dependency-aware ordering. Instructs the agent to: resolve dependency chains, identify parallel-ready items, suggest what to tackle first when multiple items are unblocked. |
| 12a.8 | **Pattern: `todo-self-check`** — LLM guidance for verifying completed items. Instructs the agent to: compare result against description, re-read the item description, mark as done only if fully satisfied, add follow-up todo if partial. |
| 12a.9 | **Integration test: full pipeline** — Agent receives goal → applies `todo-breakdown` pattern → populates todos via stdlib db primitives → S5 submits to `TodoOrchestrator` → S4 worker iterates → each item dispatched via `todo-execute-item` workflow → results update list → job completes. Verify: all items marked done, dependency order respected, failed items retried. |
| 12a.10 | **Integration test: crash recovery** — Worker crashes mid-iteration → job reloaded from JobStore → worker reads current todo state → resumes from in_progress item → completes remaining items. Verify: no duplicate execution, no lost state, final list correct. |
| 12a.11 | **Unit test: dependency resolution** — `TodoStore.get_next_pending()` returns items in topological order, skips items whose deps are not done, returns in_progress items first (resume case). |
| 12a.12 | **Remove `planner_call` from workflows** — The todo-list planner is a first-class capability invoked directly by S5, not a workflow step type. Remove `planner_call` from `StepType`/`OutcomeType` in `workflow_definition.py` and `engine.py`, remove `_handle_planner_call()`, remove the `planner_call` route from `StrategyRouter._route()` and the entire `_route_to_planner()` method, and remove `planner_call` handling from `ToolOrchestrator`. Any existing workflow YAML files using `planner_call` steps are migrated or deleted. |
| 12a.13 | **Future: unstitch S2** — Once stable, create a follow-up task to remove the hierarchical planner (`SubgoalPlanner`, `Plan`, `PlanSegment`, `MemoryGovernance` drift/repair) and route all planning through the todo-list planner. This is *not* part of 12a — it is a separate, later sprint. |

### Sprint 12b — Sub-Goal Planner (Two-Level Planning)

**Goal:** Evolve the flat todo-list planner from Sprint 12a into a **two-level planning system**. Instead of decomposing a request directly into granular tasks, the agent first decomposes into coarse **sub-goals** — major milestones on the journey to satisfying the request. Each sub-goal is then executed via a dynamic inner loop: reflect on the sub-goal, plan the *next* task needed, execute it, assess progress, and repeat until the sub-goal is complete. This replaces the single-shot `llm_call` per item with a **nested sequential refinement loop** (ReAct pattern) — no fan-out/fan-in required for V1.

#### Architecture

```
User Request
    │
    ▼
[Sub-Goal 1] ──→ reflect → plan-next-task → execute → assess → loop until complete
    │
    ▼
[Sub-Goal 2] ──→ reflect → plan-next-task → execute → assess → loop until complete
    │
    ▼
Done
```

The **outer loop** (sub-goal iteration) reuses the existing `TodoWorker` / `get_next_pending()` / `has_work_remaining()` machinery from Sprint 12a. The **inner loop** (task-level refinement per sub-goal) is new — a multi-step workflow that replaces the single `llm_call` step with a reflect-then-act cycle.

#### Schema Changes

| Task | What |
|------|------|
| 12b.1 | **Extend `todos` table** — Add `type TEXT DEFAULT 'task'` and `parent_goal_id TEXT` columns. The `type` column discriminates: `'goal'` items are sub-goals (coarse), `'task'` items are dynamically-discovered tasks within a sub-goal. `parent_goal_id` links tasks to their owning sub-goal. This keeps a single flat table — simplest migration, existing primitives mostly work. Add migration SQL and update `TodoStore.create_tables()` to the new schema. |
| 12b.2 | **Add `goal_id` column to `todo_deps`** — Add `goal_id TEXT REFERENCES todos(id)` so dependency queries can scope within a single sub-goal. The `get_next_pending` query gains a `goal_id` filter parameter. |
| 12b.3 | **Update `TodoStore` API** — Add `add_goal()`, `get_goals()`, `get_goal_tasks(goal_id)`, `get_next_pending_for_goal(goal_id)` methods. Update `add_todo()` to accept optional `type` and `parent_goal_id`. Existing callers (passing only task-level items) continue to work unchanged. |

#### New Patterns (LLM Guidance)

| Task | What |
|------|------|
| 12b.4 | **Pattern: `subgoal-breakdown`** — Replaces `todo-breakdown` for the initial decomposition. The agent analyzes the user request and identifies 3–7 coarse sub-goals (milestones, not micro-tasks). Each sub-goal has a clear completion criterion: a concrete, verifiable condition that unambiguously signals "this sub-goal is done." Sub-goals are added to the `todos` table with `type='goal'`. Dependencies between sub-goals are expressed via the existing `todo_deps` mechanism. Registered in `config/patterns/subgoal-breakdown.yaml`. |
| 12b.5 | **Pattern: `subgoal-execute`** — The inner-loop guidance for executing ONE sub-goal. This pattern drives the ReAct cycle:
1. **Anchor**: Re-state the sub-goal and its completion criterion. Read the list of already-completed tasks for this sub-goal.
2. **Reflect (adviser persona)**: Switch to a "rubber-duck adviser" tone — honest, constructive, not adversarial. Ask: "What is the single most impactful next task toward this sub-goal?" The adviser must NOT suggest the task is done unless the completion criterion is met. If no meaningful task remains AND the criterion is met, signal completion.
3. **Plan**: Create one task in the `todos` table with `type='task'` and `parent_goal_id` pointing to the current sub-goal. The task must be small enough to complete in one LLM response but large enough to be meaningful.
4. **Execute**: Run the task via the existing `todo-execute-item` workflow (single `llm_call`).
5. **Assess**: The self-check pattern (`todo-self-check`) gates completion — compare the task output against the task description. If unsatisfied, retry or create follow-up.
6. **Loop or Complete**: If the sub-goal's completion criterion is met, mark the sub-goal `done`. Otherwise, return to step 1 with accumulated progress context.
Registered in `config/patterns/subgoal-execute.yaml`. |
| 12b.6 | **Pattern: `adviser-reflect`** — The rubber-duck persona prompt. A lightweight system-prompt switch within the same agent (NOT a separate sub-agent for V1). The prompt instructs the LLM to: (a) re-read the sub-goal and its completion criterion, (b) review what tasks have been completed and their outcomes, (c) honestly assess whether the sub-goal is done — erring on the side of "not done" when uncertain, (d) if not done, suggest the single most impactful next task with a concrete description of what it should accomplish. The adviser MUST NOT suggest a task that duplicates already-completed work. Registered in `config/patterns/adviser-reflect.yaml`. |

#### Workflow Changes

| Task | What |
|------|------|
| 12b.7 | **New workflow: `subgoal-execute-loop`** — A multi-step cyclic workflow that implements the inner loop for one sub-goal. Steps: `anchor_subgoal` (llm_call — restate goal + progress) → `adviser_reflect` (llm_call with adviser persona) → `condition` (branch: if "complete" → `mark_subgoal_done` tool_execute → `__end__`; if "next_task" → `create_next_task` tool_execute → `execute_task` sub_workflow → `assess_task` llm_call → loop back to `anchor_subgoal`). The loop is bounded by a `max_iterations` guard (default 10). Registered in `config/workflows/subgoal-execute-loop.yaml`. |
| 12b.8 | **Update `todo-execute-item` workflow** — Now used for individual TASK execution within the sub-goal inner loop. Receives the task's title, description, and the parent sub-goal context (for anchoring). The prompt is extended to include "You are working toward sub-goal: {context.parent_goal_title} — {context.parent_goal_description}." This keeps task execution anchored to the larger goal. |

#### Worker & Orchestrator Changes

| Task | What |
|------|------|
| 12b.9 | **Update `TodoWorker`** — Distinguish goal items from task items at `get_next_pending()` time. When the next pending item has `type='goal'`, dispatch the `subgoal-execute-loop` workflow instead of `todo-execute-item`. When the item has `type='task'`, use the existing single-shot workflow. The worker's existing retry logic, crash recovery, and `cognitive_state` persistence (db_path) continue to work unchanged — the inner loop is just a different workflow, bounded by the same execution cycle timeout. |
| 12b.10 | **Update `TodoOrchestrator`** — No structural changes needed — the orchestrator submits jobs and the worker handles the rest. Add a `max_iterations_per_goal` configuration parameter (default 10) injected into the worker for the inner-loop guard. |

#### Guardrails (Risk Mitigation)

| Risk | Mitigation |
|------|------------|
| **Infinite inner loop** — agent never declares sub-goal done | Hard cap: `subgoal-execute-loop` workflow has `max_iterations` (default 10). After exhausting iterations, the sub-goal is marked `failed` with reason "exceeded max iterations." The outer loop continues to the next sub-goal. The `_StepFailedError` mechanism from 12a handles this naturally. |
| **Hallucinated completion** — agent claims sub-goal done without satisfying the criterion | Two gates: (1) The `adviser-reflect` pattern requires the completion criterion to be explicitly verified — the adviser must cite evidence, not just assert. (2) `todo-self-check` runs against the sub-goal itself after the inner loop signals completion, comparing the accumulated task outputs against the sub-goal's stated criterion. If either gate fails, the sub-goal stays in_progress. |
| **Context window bloat** — accumulated conversation across many inner-loop iterations | **Progress compaction**: After each task completes, `subgoal-execute-loop` summarizes the task outcome into a one-line "progress entry" stored in the sub-goal's description field (appended). The adviser sees the compacted progress, not the full conversation history. The `anchor_subgoal` step reads this compacted state. Tasks are also stored as individual rows for traceability but the LLM context only sees the summary. |
| **Task drift** — inner loop loses sight of the sub-goal | Every inner-loop iteration begins with `anchor_subgoal` — restating the sub-goal title, description, and completion criterion. The task execution prompt also includes the parent sub-goal context. This is triple-anchored: (1) adviser prompt, (2) task creation prompt, (3) task execution prompt. |
| **Over-decomposition** — creating 50 micro-tasks for one sub-goal | `adviser-reflect` guidance: "Suggest the single most impactful next task — a meaningful unit of work, not every micro-step. If the remaining work is trivial, consider whether the sub-goal is actually done." The `max_iterations` cap is a backstop. |
| **Dependency deadlock** — task depends on another task within the same sub-goal but both are pending | The sub-goal inner loop is intentionally sequential (one task at a time). If a task discovers it needs prerequisite work, it can add a follow-up task with a dependency via `add_dep()`. The `get_next_pending_for_goal()` respects deps within the sub-goal. This is the same dependency resolution as 12a, scoped to one sub-goal. |

#### Testing

| Task | What |
|------|------|
| 12b.11 | **Unit test: schema migration** — Verify `TodoStore` creates tables with new `type` and `parent_goal_id` columns. Existing tests with task-only items pass unchanged. New tests: `add_goal()`, `get_goals()`, `get_next_pending_for_goal()` with interleaved goals and tasks, task dependency resolution within a goal. |
| 12b.12 | **Unit test: inner loop boundedness** — Simulate `subgoal-execute-loop` with a mock that never signals completion. Verify the workflow stops at `max_iterations` (10) and marks the sub-goal `failed`. Verify the outer loop continues to the next sub-goal. |
| 12b.13 | **Unit test: adviser persona** — Verify the `adviser-reflect` pattern prompt includes: (a) re-read sub-goal, (b) review progress, (c) completion criterion check, (d) suggest next task. Verify it explicitly forbids duplicating completed work. |
| 12b.14 | **Unit test: progress compaction** — Verify that after N inner-loop iterations, the sub-goal's description contains compacted progress entries (not raw conversation). Verify the adviser prompt receives the compacted text, not the full history. |
| 12b.15 | **Unit test: self-check gating** — Sub-goal signals completion but `todo-self-check` finds the completion criterion unmet → sub-goal stays `in_progress`, inner loop continues. Sub-goal signals completion and criterion is met → sub-goal marked `done`. |
| 12b.16 | **Integration test: two-level pipeline** — Agent receives a multi-faceted request → applies `subgoal-breakdown` pattern → populates 3 sub-goals with completion criteria → S5 submits to `TodoOrchestrator` → worker iterates sub-goals → for each sub-goal, inner loop reflects, plans tasks, executes, assesses → all sub-goals complete → job done. Verify: correct sub-goal ordering, task-level dependency resolution, inner loop boundedness, progress compaction, self-check gating. |
| 12b.17 | **Integration test: crash recovery with inner loop** — Worker crashes mid-inner-loop (e.g., after task 2 of 4 within a sub-goal). Job reloaded from JobStore → worker reads cognitive_state (db_path) → resumes sub-goal from in_progress → inner loop restarts with compacted progress → completes remaining tasks → advances to next sub-goal. Verify: no duplicate task execution, no lost progress, final sub-goal states correct. |

#### V2 Considerations

The following are explicitly deferred to a future sprint — they are NOT part of 12b:

| Concern | Why Deferred | What V2 Would Require |
|---------|-------------|----------------------|
| **Fan-out / parallel task execution** | The sequential inner loop is sufficient for V1. Parallelism requires: (a) a task-graph executor that can dispatch independent tasks concurrently, (b) result merging/conflict resolution when parallel tasks touch the same files, (c) an `ExecutionStage` that supports concurrent worker slots. This is a significant infrastructure investment — the S4 worker model is currently single-threaded per job. | Multi-slot S4 workers, task parallelism detector (identifies tasks with no mutual deps within a sub-goal), merge conflict resolution. |
| **Separate adviser sub-agent** | For V1, the adviser is a prompt switch within the same agent — zero coordination overhead. A separate agent requires: (a) inter-agent message passing, (b) context transfer (the adviser needs to see the sub-goal + progress), (c) the S4 event substrate to support agent-to-agent communication. The value-add (independent reasoning without polluting the main agent's context) is real but the complexity cost is high for V1. | Inter-agent communication via S4 events, agent spawning from workflows, context snapshot/restore for handoff. |
| **Sub-goal replanning** | The agent cannot currently modify sub-goals mid-execution (e.g., "this sub-goal was wrong, we need a different approach"). V1 treats sub-goals as fixed once planned. Dynamic replanning requires: (a) the ability to insert/remove/reorder sub-goals in the outer list, (b) the adviser to detect when the current approach is futile, (c) a replanning trigger that pauses the inner loop and invokes `subgoal-breakdown` again scoped to the remaining work. | Sub-goal modification primitives (`update_goal`, `delete_goal`, `insert_goal`), replanning trigger detection, partial-plan resumption. |
| **Cross-sub-goal learning** | Lessons learned in sub-goal 1 aren't automatically applied to sub-goal 2. V2 could: (a) append "lessons learned" to the cognitive_state after each sub-goal completes, (b) inject those lessons into the adviser context for subsequent sub-goals. This requires the learning subsystem (Y.8) or a simpler cross-sub-goal note-passing mechanism. | Cognitive_state enrichment with per-sub-goal post-mortems, adviser prompt injection of prior sub-goal lessons. |

### Sprint 13 — Hardening & Resilience

**Goal:** Production-grade resilience, health monitoring, and self-healing.

| Task | What |
|------|------|
| 13.1 | Classify loop health — healthy, stalled, poisoned |
| 13.2 | Detect stalled loops → auto-abort |
| 13.3 | Auto-downgrade behaviour on failure |
| 13.4 | Global watchdog for agent loops |
| 13.5 | Auto-scaling hooks |
| 13.6 | Panic reporting |
| 13.7 | Recovery drills |
| 13.8 | Document failure modes |

### Sprint 14 — Observability & DX

**Goal:** Structured logging, metrics, tracing, and developer tooling.

| Task | What |
|------|------|
| 14.1 | Structured logging (correlation_id through every layer) |
| 14.2 | Metrics exporter (workflow duration, failure rate, LLM latency) |
| 14.3 | Tracing spans (per step, per workflow, per agent invocation) |
| 14.4 | Flamegraph timings |
| 14.5 | Local dev CLI improvements |
| 14.6 | Replay tooling for debugging |
| 14.7 | Config inspector |
| 14.8 | Skill inspector |
| 14.9 | Agent inspector |
| 14.10 | End-to-end smoke tests |

### Sprint 15 — Polish & Production Readiness

| Task | What |
|------|------|
| 15.1 | Security review of skills |
| 15.2 | Security review of fetch stack |
| 15.3 | LLM prompt hardening |
| 15.4 | Config profiles — dev, prod, paranoid |
| 15.5 | Backward-compatible APIs |
| 15.6 | Performance tuning |
| 15.7 | Load testing |
| 15.8 | Graceful degradation strategy |
| 15.9 | Disaster recovery story |
| 15.10 | Architecture doc for future contributors |

### Sprint 16 — Local Custom Overlay (Personal Workspace Isolation)

*Keep the repo clean of opinionated/experimental/test content by adding gitignored "custom" subfolders across all configurable namespaces.*

| Task | What |
|------|------|
| 16.1 | Add `custom/` subfolder to `config/workflows/`, `config/agents/`, and update loaders to scan both the standard dir and the `custom/` sibling |
| 16.2 | Add `custom/` subfolder to `plugins/` (for MCP, skills, primitives, etc.) and update `PluginLoader` to scan both |
| 16.3 | Add `custom/` to `.gitignore` so local experiments never pollute the repo |
| 16.4 | Update boot sequence / `composition_root.py` to merge standard + custom artifacts with priority semantics (custom wins on conflict) |
| 16.5 | Write a `docs/custom_workflows.md` guide explaining the overlay pattern for users who fork the repo |

### Sprint 17 — LLM Provider Abstraction

*Each LLM provider has unique quirks — tool name sanitisation (dots→underscores), `tool_choice` defaults, schema handling (e.g. `required` field injection), token limits, streaming vs non-streaming. These are currently patched ad-hoc across the codebase. This sprint builds a proper abstraction layer.*

| Task | What |
|------|------|
| 17.1 | Audit all provider-specific workarounds — search for `tool_choice`, `required` field hacks, name sanitisation, `stop_reason` handling, and any `if provider == "deepseek"`-style branching |
| 17.2 | Design an `LLMProviderAdapter` interface — a thin shim that translates provider-native schemas into a canonical S1 contract. Each provider implements one adapter; S1 client talks only to the adapter |
| 17.3 | Adapter — **OpenAI-compatible** (covers OpenAI, DeepSeek, Together, Groq, etc.) |
| 17.4 | Adapter — **Anthropic** (handles `stop_reason` vs `finish_reason`, tool_use content blocks) |
| 17.5 | Adapter — **Gemini** (handles `functionCall` content parts, different error schema) |
| 17.6 | Adapter — **Mistral** (handles `tool_calls` format differences) |
| 17.7 | Move provider-specific config (tool_choice default, name sanitisation rules) into per-provider adapter config, not the S1 client |
| 17.8 | Write integration tests — each adapter with its real provider (or recorded fixture), covering: tool call with params, tool call with empty args, no-tool response, error propagation |
| 17.9 | Regression test — full suite passes with all providers |
| 17.10 | Document adapter architecture in `docs/architecture/provider_adapters.md` |

### Sprint 18 — Supervisor Refactor (Breakup)

*`src/agent/supervisor.py` currently mixes 5+ concerns in a single 600+ line file: agent orchestration and routing, HITL confirmation state machine, hallucination guard, workflow invocation (`/invoke-workflow`), tool execution and follow-up (phase 2), and AgentState management. This sprint breaks each concern into its own module, leaving `supervisor.py` as a thin orchestrator. Separation of concerns makes testing easier — each module gets isolated tests — and reduces cognitive load when editing any single concern.*

| Task | What |
|------|------|
| 18.1 | Extract **hallucination guard** to `src/agent/guards/hallucination_guard.py` — move `_ACTION_CLAIM_RE`, `_apply_hallucination_guard()` and any related regex helpers. Keep the `_AFFIRMATIVE_RE` in the HITL module (18.2) since it's about confirmation, not hallucination detection | ✅ |
| 18.2 | Extract **HITL confirmation** to `src/agent/hitl_manager.py` — move `_AFFIRMATIVE_RE`, `_run_confirmed_skills()`, `_has_side_effect_tool_calls()`, `_format_hitl_prompt()`, and the `WAITING` state transitions. The HITL manager owns the lifecycle: pending → confirmed → execute → done | ✅ |
| 18.3 | Extract **tool orchestrator** to `src/agent/tool_orchestrator.py` — move phase-1 tool execution loop, phase-2 follow-up LLM call (including the `tool_context` assembly), and primitive-result collection. The supervisor should just call `orchestrator.execute_tool_plan(tool_calls)` and get back `(reply, metadata_deltas)` | ✅ |
| 18.4 | Extract **workflow invoker** to `src/agent/workflow_invoker.py` — move `_handle_invoke_workflow()` and any `/invoke-workflow` directive parsing. Returns structured workflow execution results that the supervisor inserts into the response | ✅ |
| 18.5 | Slim `supervisor.py` to core orchestration: `_process_input()` → route → HITL check → tool orchestration → guard → workflow invocation. Each step delegates to the appropriate module. The state machine (`_ACTIVATED → _WAITING → _PROCESSING → _IDLE`) stays in the supervisor since it governs the overall flow | ✅ |
| 18.6 | Write isolated unit tests for each extracted module — hallucination guard (known action phrases, `/invoke-workflow` exemptions, safe replies), HITL manager (affirmation regex matches, side-effect detection, state transitions), tool orchestrator (tool call execution, follow-up with/without tools, error propagation), workflow invoker (directive parsing, execution results) | ✅ |
| 18.7 | Full integration test — CLI session covering: search → read → HITL confirm → delete → follow-up reply with tool call → hallucination guard on tool-less claim | ✅ |

### Sprint 19 — Conversation Quality & Prompt Engineering

*Sprint 18 fixes the supervisor's orchestration. Sprint 19 fixes what the LLM actually *says*. The biggest UX improvements will come from prompt quality, not routing code — system prompts that teach better error recovery, conversation history that doesn't drown the LLM in noise, and error handling that recovers gracefully instead of repeating the same non-answer.*

| Task | What |
|------|------|
| 19.1 | **System prompt audit** — Review all agent personas in `config/agents/*.yaml`. Ensure each prompt explicitly teaches: (a) graceful error recovery ("if a tool 404s, tell the user and offer alternatives, don't keep retrying"), (b) tool selection guidance ("prefer search → read → act flow"), (c) when to ask clarifying questions vs. infer |
| 19.2 | **Sliding-window conversation history** — Replace flat list in `SessionedAdapter` with a smarter strategy: keep full recent N turns, summarize older turns into a compressed memory slot. Prevents the LLM from losing track in long sessions |
| 19.3 | **Error recovery prompt pattern** — When a tool call fails, inject structured guidance into the prompt (not just raw `[Primitive ... → {error}]`). E.g., "The tool failed. You may: (a) retry with modified params, (b) explain the issue and suggest alternatives, (c) ask the user what to do next." |
| 19.4 | **Conversation-state anchoring** — After each side-effect tool call (delete, send, update), inject a plain-English summary into history so the LLM can recall what happened without parsing tool output. E.g., "Action taken: deleted email from Google (security alert)" |
| 19.5 | **Regression test suite** — Record real CLI sessions (good and bad), replay them as regression tests. Ensure the fixes from Sprint 17 (this sprint) don't regress. Each test asserts: no annotation leakage, hallucination guard fires correctly, follow-up tools are available, error recovery is graceful |
| 19.6 | **Field-testing & tuning** — Run 10+ real conversation flows through the CLI: search → read → reply (with HITL), search → delete (with HITL), multi-turn with agent switching, error cases (bad search, already-deleted message). Tune prompts based on observed failures. Document findings in `docs/operations/conversation_quality.md` |

---

## 🔮 Future / Exploration

These are forward-looking capabilities that the architecture supports but are not yet on the roadmap.

### Y.1 — Meta-Planning & Self-Reflection
- Agents analyze their own plans and past workflow executions
- Self-improvement loops — "what could I have done better?"

### Y.2 — Long-Term Memory & Knowledge Graphs
(note: see section Z before considering this section)
- Persistent memory across sessions
- Knowledge graph of entities, decisions, and past outcomes
- Semantic retrieval for context injection

### Y.3 — Multi-Agent Societies
- Multiple agents with specialized roles
- Agent-to-agent communication via S4 event substrate
- Delegation, escalation, and collaboration patterns

### Y.4 — Emergent Workflow Authoring
- Agents create and repair YAML workflow files
- Codify successful multi-step patterns as repeatable workflows
- "I did this task well — now I have a workflow for it"

### Y.5 — Agent-Authored Workflow Discovery
- Agents register new workflows they've created
- Workflow marketplace / library within the system
- Agents select workflows authored by other agents

### Y.6 — Autonomy & Governance
- Approval gates for high-risk workflow steps
- Audit trails for all agent actions
- Policy enforcement at the S5 routing layer

### Y.7 — Patterns (LLM-Level Reusable Instructions) ✅ → Sprint P1–P3

**Concept:** A "pattern" is a reusable, LLM-readable instruction template — like a workflow but expressed as natural-language/in-context instructions rather than executable step graphs. Patterns codify successful emergent behaviour that is too complex, non-deterministic, or context-sensitive to be expressed as a YAML workflow.

**Now being implemented:** See Sprint P1–P3 above (between Sprint 9a and Sprint 10). P1 covers definition & registry, P2 covers agent integration, P3 covers workflow & learning integration.

**Concept:** A "pattern" is a reusable, LLM-readable instruction template — like a workflow but expressed as natural-language/in-context instructions rather than executable step graphs. Patterns codify successful emergent behaviour that is too complex, non-deterministic, or context-sensitive to be expressed as a YAML workflow.

| Aspect | Workflows | Patterns |
|--------|-----------|----------|
| Form | Declarative YAML step graph | Natural-language instruction template |
| Execution | Engine-driven state machine | LLM-interpreted guidance |
| Determinism | High — explicit steps, conditions, transitions | Low — LLM decides how to apply the pattern |
| Best for | Repeatable, predictable processes | Creative, nuanced, or context-heavy tasks |

**Key properties:**
- **Callable by agents** — an agent can say "apply pattern X" and receive instructions for how to handle a situation
- **Callable by workflows** — a workflow step type `apply_pattern` that injects pattern instructions into an LLM call context
- **Storage** — YAML/JSON files in `config/patterns/` with a `description` + `instructions` + optional `examples` field
- **Discovery** — registered in a PatternRegistry, discoverable by agents and the planner

**Examples:**
- "How to handle a user asking for a refund" — multi-step negotiation pattern
- "How to escalate a security-related user request" — routing with context preservation
- "How to debug a failing test" — investigative checklist that adapts based on findings

**⚠️ Concerns:**
- **Adherence vs adaptation tension** — agents may ignore patterns if they're too prescriptive, or follow them rigidly when adaptation is needed. Need clear guardrails: when *must* the pattern be followed vs when *may* the agent adapt it?
- **Pattern bloat** — without curation, patterns could accumulate into a graveyard of unused instruction files. A usage-based pruning mechanism (archive patterns not referenced in N days) should be considered from the start.
- **Quality variance** — auto-generated patterns (from Y.8) may be lower quality than hand-authored ones. A review gate or confidence threshold before a pattern is discoverable may be necessary.

### Y.8 — Learning Subsystem (Emergent Codification Engine)

**Concept:** An async observer that watches agentic emergent actions. When an agent performs a successful bespoke action (not already covered by a workflow, skill, or pattern), the learning subsystem considers whether that action should be codified as a reusable artifact.

**Flow:**

```
Agent performs bespoke action successfully
    │
    ▼
Learning Subsystem (async observer)
    │
    ├── Is it simple and deterministic?
    │   └── Yes → Create Workflow (YAML step graph)
    │
    ├── Is it a primitive, well-defined capability?
    │   └── Yes → Create Skill (executable tool)
    │
    └── Is it complex, nuanced, or context-sensitive?
        └── Yes → Create Pattern (LLM instruction template)
```

**Key properties:**
- **Async observer** — does not block or slow down the primary execution path. Watches via S4 event subscription or post-hoc log analysis
- **Codification decision criteria** (tunable):
  - *Confidence* — how reliably did the action succeed? (e.g., >90% over 5+ attempts)
  - *Reusability* — how likely is this action to be useful again? (parametric similarity to past requests)
  - *Complexity* — can it be expressed as a workflow? a skill? or does it need a pattern?
- **Artifact lifecycle**:
  1. **Candidate** — identified but not yet reviewed
  2. **Draft** — auto-generated YAML/instructions, pending human or agent review
  3. **Published** — registered and available for use
  4. **Deprecated/Removed** — superseded or no longer useful
- **Workflow creation** — for simple, repeatable patterns, generates a YAML workflow file with the observed steps
- **Skill creation** — for primitive, well-defined capabilities, generates a registered skill (e.g., a fetch + parse wrapper)
- **Pattern creation** — for complex or context-heavy behaviour, generates a pattern file with natural-language instructions
- **Human-in-the-loop** — optional approval gate before publishing any auto-generated artifact
- **Calls to Y.4/Y.7** — the learning subsystem is the *producer* of emergent workflows (Y.4) and patterns (Y.7)

**⚠️ Concerns:**
- **Signal detection is the hard part** — how do you reliably determine "success"? User satisfaction? Task completion? Agent self-assessment? Without a trustworthy feedback signal, the subsystem will codify bad behaviour with high confidence. Needs careful thought before building.
- **Three-way classification is ambitious** — having the system autonomously decide "this is a workflow vs a skill vs a pattern" is a non-trivial classification problem. Recommend starting with the system surfacing *candidates* for human (or reviewer-agent) decision, then automating once there's enough labelled data.
- **Sequencing dependency** — the learning subsystem depends on mature observability (Sprint 14), durable execution (Sprint 11), and stable base layers that produce reliable telemetry. Building it too early means building on shifting sand. Recommended post-Sprint-15.
- **Feedback loop risk** — if the subsystem creates artifacts that are then used by agents, which are then observed by the subsystem, you risk reinforcing its own biases. Need a mechanism to detect and break circular codification.

### Z — Multi-Tier Memory Architecture

**Goal:** Evolve beyond simple in-memory conversation history into a layered memory system with compression, retrieval, and forgetting — enabling long-running, context-rich interactions.

**Concept:** A Memory Controller sits between the agent and its context window, managing what goes in (recent messages, retrieved chunks), what gets compressed (summaries, reflection notes), what persists externally (vector DB, file store, episodic records), and what gets pruned.

#### Z.1 — Short-Term (Context Window)

| Task | What |
|------|------|
| Z.1.1 | Template-based system prompt injection (persona, instructions, constraints) |
| Z.1.2 | Sliding window of recent `user`/`assistant` messages (configurable N) |
| Z.1.3 | Retrieved memory chunk injection at query time (semantic + episodic) |
| Z.1.4 | Token budget tracking — allocate tokens across system / window / retrieved chunks |

#### Z.2 — Compression (Summaries & Reflection)

| Task | What |
|------|------|
| Z.2.1 | Running structured summary summarizer — periodically condense older turns |
| Z.2.2 | Reflection notes — agent-generated observations about goals, blockers, decisions |
| Z.2.3 | Tiered eviction — oldest raw messages → summary → discarded |
| Z.2.4 | Compression triggers — token threshold, idle time, turn count |

#### Z.3 — External Memory (Long-Term Storage)

| Task | What |
|------|------|
| Z.3.1 | Vector DB integration — semantic search over past conversations and documents |
| Z.3.2 | File store — tool outputs, logs, generated artifacts indexed by session |
| Z.3.3 | Episodic records — structured recall of past sessions (goals, outcomes, errors) |
| Z.3.4 | Cross-session retrieval — "how did I solve this last week?" |

#### Z.4 — Memory Controller

| Task | What |
|------|------|
| Z.4.1 | Controller policy engine — configurable rules for keep / compress / retrieve / forget |
| Z.4.2 | Decide what to keep in context window vs evict to summary |
| Z.4.3 | Decide when to compress — triggers summarization of eligible windows |
| Z.4.4 | Decide what to retrieve — semantic query construction from current turn context |
| Z.4.5 | Decide what to forget — TTL-based, relevance-threshold, or explicit agent-directed pruning |
| Z.4.6 | Memory inspection tools — `:memory` CLI command to view current context, summary, and linked records |

---

## Cross-Cutting Concerns

### N.1 — Fix CI Architecture Check
**Problem:** `ci_architecture_check.py` errors, providing unreliable signal.

**Goal:** Script runs cleanly, 0 Critical, 0 High, gated in CI.

### N.2 — Reduce HIGH Architecture Issues
**Problem:** 279 HIGH issues in last audit — blocks CI.

**Goal:** Triage, fix genuine issues, exempt false positives. Target: 0 Critical, 0 High.

### N.3 — Integration Testing Foundation
**Problem:** No integration tests for full pipeline.

**Goal:** Harness + first suite of integration tests, running in CI.

### N.4 — Gateway Hardening
**Problem:** Gateway exists as concept but no real external ingress hits it.

**Goal:** At least one real path end-to-end (CLI → Gateway → S5 → response). Document gaps for other channels.

### N.5 — Pipeline Validation
**Problem:** Large pieces work in isolation, wiring never tested end-to-end.

**Goal:** Wire real components, exercise critical paths, document readiness matrix.

---

## Release Milestones

| Release | Sprints | Theme |
|---------|---------|-------|
| 1 | 1–3 | Foundation + Agent Runtime + Workflow Engine |
| 2 | 4 | Planner Call Step |
| 3 | 5–6 | Pipeline Wiring + Event-Driven Triggers |
| 4 | 7–9 | Operations + Human-in-the-Loop + Agent Selection |
| 5 | 10 | Stratum Isolation Refactor |
| 6 | 11–12 | Durable Execution + Real Skills |
| 6a | 12a | SQL Structured Data Skill (Flat Todo-List Planner) |
| 6b | 12b | Sub-Goal Planner (Two-Level Planning) |
| 7 | 13 | Resilience & Self-Healing |
| 8 | 14 | Observability & DX |
| 9 | 15 | Polish & Production Readiness |
