# Agent Task Decomposition — Implementation Roadmap

> **Status:** Plan — ready for implementation  
> **Sprint:** Agent Decomposition A1  
> **Depends on:** S4 job system, S5 agent runtime, S2 planner, agent-deferral (D1)  
> **Target:** Deterministic fan-out/fan-in with dependency-aware DAG execution on S4

---

## Implementation Quick-Start (Read This First)

### What Exists vs. What's New

| Existing (use as-is) | Must Modify (add fields/methods) | Must Create (new files) |
|---|---|---|
| `Queue.push()`/`pop()` | `Job` — add 8 fields (job_type, parent_job_id, ...) | `src/agent/types/decomposition.py` |
| `AgentState` / `LifecycleState` | `JobState` — add BLOCKED state | `src/platform/runtime/join_handle.py` |
| `AgentRegistry` | `LifecycleState` — add AWAITING_CHILDREN | `src/platform/runtime/stores/join_store.py` |
| `AgentMetadata.defer_to` | `s2_planner.py` — add S2PlanDecomposer protocol | `src/platform/runtime/stores/in_memory_join_store.py` |
| `Supervisor.defer_to_agent()` | `config_system.py` — add decomposition section | `src/agent/decomposition/orchestrator.py` |
| Deferral: `DeferralResolver`, `DepthGuard`, `ContextBridge` | `supervisor.py` — add `decompose_task()` method | `src/agent/decomposition/dag_validator.py` |
| `JobStore`, `AgentStateStore` (store pattern) | Scheduler — add BLOCKED_ON_JOIN dispatch logic | `src/agent/decomposition/fan_out.py` |
| `Job` BaseModel pattern | | `src/agent/decomposition/fan_in.py` |
| | | `src/agent/decomposition/atomicity.py` |
| | | `src/agent/decomposition/__init__.py` |

### Implementation Order (Dependency Chain)

```
1. Types first           → src/agent/types/decomposition.py
2. Job model + state     → modify job.py + job_state.py (add fields, BLOCKED)
3. Config                → modify config_system.py (add decomposition section)
4. JoinHandle + stores   → create join_handle.py, join_store.py, in_memory_join_store.py
5. Lifecycle state       → modify agent_state.py (add AWAITING_CHILDREN)
6. Planner protocol      → modify s2_planner.py (add S2PlanDecomposer)
7. DAG validator         → create dag_validator.py
8. Atomicity             → create atomicity.py
9. Fan-out               → create fan_out.py
10. Fan-in               → create fan_in.py
11. Orchestrator         → create orchestrator.py
12. __init__              → create __init__.py
13. Supervisor method    → modify supervisor.py (add decompose_task)
14. Scheduler            → modify scheduler (BLOCKED_ON_JOIN + dependency-aware dispatch)
```

**Golden rule:** Every file path in this document starts from `C:\Users\mikut\Code\vai-core\`. All imports use absolute paths (`from src.agent.types.decomposition import ...`).

---

## 1. Architecture Overview

### 1.1 Where Decomposition Fits

Agent task decomposition is a **horizontal capability** that spans S2 (planning), S5 (agent runtime), and S4 (durable execution). No new subsystems are created. Every operation flows through existing S4 jobs, queues, and workers.

```
                           S5 Agent Runtime
                                │
                    ┌───────────┼───────────┐
                    │           │           │
              ┌─────▼─────┐ ┌──▼───┐ ┌─────▼─────┐
              │ S2 Planner │ │Agent │ │ Deferral  │
              │ (pure fn)  │ │Loop  │ │ Resolver  │
              └─────┬─────┘ └──┬───┘ └─────┬─────┘
                    │           │           │
       Decomposition│           │           │
       Graph (DAG)  │  non-atomic           │
                    │  detection            │
              ┌─────▼───────────▼───────────▼─────┐
              │        DecompositionOrchestrator   │
              │  (new, thin, inside S5)            │
              │  ┌─────────────────────────────┐   │
              │  │ 1. Detect non-atomic task   │   │
              │  │ 2. Call S2 Planner → DAG    │   │
              │  │ 3. Fan-out → N child jobs   │   │
              │  │ 4. Create JoinHandle        │   │
              │  │ 5. Submit continuation job  │   │
              │  │ 6. Fan-in → merge results   │   │
              │  └─────────────────────────────┘   │
              └──────────────┬─────────────────────┘
                             │
                    ┌────────▼────────┐
                    │     S4 Platform │
                    │  ┌───────────┐  │
                    │  │  Queue    │  │
                    │  ├───────────┤  │
                    │  │ Worker    │  │
                    │  │  Pool     │  │
                    │  ├───────────┤  │
                    │  │ Control   │  │
                    │  │  Plane    │  │
                    │  ├───────────┤  │
                    │  │ Job Store │  │
                    │  ├───────────┤  │
                    │  │ Join      │  │
                    │  │  Store    │  │← NEW
                    │  └───────────┘  │
                    └─────────────────┘
```

### 1.2 Key Principle

**All decomposition runs through S4 jobs, queues, and workers.** S5's `DecompositionOrchestrator` calls S2 for the plan (pure computation), then submits jobs to S4. S5 never directly invokes child agents — it enqueues jobs that workers pick up and route to agents.

### 1.3 Relationship to Existing Agent Deferral

Agent deferral (D1) handles **single-agent, sequential** hand-off: A → B → A.  
Agent decomposition (A1) handles **multi-agent, parallel** fan-out: A → [B, C, D] → A.

Both use the same S4 infrastructure. Deferral is a special case of decomposition where the DAG has exactly one child with no siblings.

---

## 2. Decomposition Trigger Logic

### 2.1 Atomicity Test

An agent determines a task is non-atomic by applying three conditions. The task is **atomic** only if ALL three are true:

| Condition | Meaning | Example (atomic) | Example (non-atomic) |
|-----------|---------|-------------------|----------------------|
| One action | A single verb with a single object | "Fetch user 42" | "Audit and fix all security issues" |
| One deliverable | Produces exactly one output artifact | Return dict of user data | Generate 5 reports + a summary |
| One acceptance criterion | Success/failure is binary and checkable in one step | HTTP 200 or error code | "All tests pass AND coverage > 80%" |

### 2.2 Trigger Flow

```
Agent Loop tick
    │
    ├── task passes atomicity test?
    │       │
    │       ├── YES → execute normally (single job, single agent)
    │       │
    │       └── NO  → call DecompositionOrchestrator.decompose(task)
    │                    │
    │                    ├── 1. Build DecompositionRequest
    │                    ├── 2. Call S2 PlanDecomposer (pure)
    │                    ├── 3. Validate returned DAG
    │                    ├── 4. Fan-out: enqueue child jobs
    │                    ├── 5. Create JoinHandle
    │                    ├── 6. Enqueue ContinuationJob
    │                    └── 7. Agent suspends (AWAITING_CHILDREN)
    │
    ▼
```

### 2.3 Routing to the Planner

The `DecompositionOrchestrator` (S5) constructs:

```python
DecompositionRequest(
    parent_task=task_description,       # str: the full non-atomic task
    parent_context=agent.memory_snapshot(),  # MemorySnapshot from S2
    available_agents=list(agent_registry.list_ids()),  # [str, ...]
    constraints={
        "max_depth": config.max_decomposition_depth,       # default: 2
        "max_children": config.max_decomposition_children, # default: 8
    }
)
```

This is handed to `PlanDecomposer.decompose()` (S2, pure function). S2 returns a `DecompositionPlan` (see Section 3).

---

## 3. Planner Output Contract

### 3.1 DecompositionPlan Schema

```python
# Location: src/strategy/planning/decomposition_plan.py
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class SubtaskSpec:
    """A single atomic subtask in a decomposition DAG."""
    id: str                              # Unique within the plan (e.g., "subtask-0")
    description: str                     # Atomic action description
    target_agent_id: str | None = None   # Agent to execute (None = use parent's agent)
    target_skill_id: str | None = None   # Skill to invoke (None = let agent decide)
    arguments: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)  # Subtask IDs that must complete first
    priority: int = 0                    # Higher = earlier when dependencies satisfied
    timeout_seconds: int = 300           # Per-subtask timeout
    max_retries: int = 2                 # Per-subtask retry limit


@dataclass(frozen=True)
class DecompositionPlan:
    """Output of S2 PlanDecomposer.decompose(). Pure data, no I/O."""
    plan_id: str
    parent_task: str
    subtasks: list[SubtaskSpec]          # All subtasks in the DAG
    merge_strategy: str                  # "concat" | "summarize_llm" | "select_best" | "custom"
    merge_agent_id: str | None           # Agent to perform merge (None = parent agent)
    merge_prompt_template: str | None    # LLM prompt for merge (used when merge_strategy="summarize_llm")
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 3.2 Validation Rules (enforced at creation time)

1. All `id` values must be unique within `subtasks`.
2. All `depends_on` entries must reference valid `id` values from within the same plan.
3. The dependency graph must be acyclic (validated by DFS).
4. No subtask may depend on itself (`id` not in own `depends_on`).
5. `merge_strategy` must be one of the known strategies (see Section 9).

---

## 4. Dependency Graph Requirements

### 4.1 DAG Rules

The `DecompositionPlan.subtasks` list forms a directed acyclic graph:

- **Nodes** = `SubtaskSpec.id`
- **Edges** = `SubtaskSpec.depends_on` (A depends on B → edge B→A)

Rules enforced by the planner (S2) and validated by the orchestrator (S5):

| Rule | Enforcement |
|------|-------------|
| No circular dependencies | DFS cycle detection — planner MUST produce acyclic graph |
| No missing dependencies | Every `depends_on` entry MUST resolve to an `id` in the plan |
| Semantically correct edges | Planner infers: if subtask B consumes output of subtask A, B.depends_on contains A |
| Independent tasks = empty depends_on | If tasks can run concurrently, their `depends_on` is `[]` |
| No self-dependency | `id` must not appear in own `depends_on` |

### 4.2 DAG Validation (S5 orchestrator, before fan-out)

```python
def validate_dag(subtasks: list[SubtaskSpec]) -> None:
    """Validate DAG invariants. Raises ValueError on violation."""
    ids = {s.id for s in subtasks}
    
    # Check uniqueness
    if len(ids) != len(subtasks):
        raise ValueError("Duplicate subtask IDs")
    
    # Check missing deps and self-deps
    for s in subtasks:
        for dep in s.depends_on:
            if dep not in ids:
                raise ValueError(f"Subtask {s.id} depends on unknown {dep}")
            if dep == s.id:
                raise ValueError(f"Subtask {s.id} depends on itself")
    
    # Cycle detection via DFS
    _check_cycles(subtasks)
```

### 4.3 Example DAG

```
     subtask-0 (empty depends_on)
         │
    ┌────┴────┐
    ▼         ▼
subtask-1  subtask-2
    │         │
    └────┬────┘
         ▼
     subtask-3 (depends_on=["subtask-1", "subtask-2"])
```

Serialised:
```json
{
  "subtasks": [
    {"id": "subtask-0", "description": "Clone repository", "depends_on": []},
    {"id": "subtask-1", "description": "Run linter", "depends_on": ["subtask-0"]},
    {"id": "subtask-2", "description": "Run tests", "depends_on": ["subtask-0"]},
    {"id": "subtask-3", "description": "Generate report", "depends_on": ["subtask-1", "subtask-2"]}
  ]
}
```

---

## 5. S4 Fan‑Out Implementation

### 5.1 Fan-Out Flow

The `DecompositionOrchestrator` (S5) receives a validated `DecompositionPlan` from S2 and fans out by enqueuing one S4 job per subtask.

```
DecompositionOrchestrator.fan_out(plan: DecompositionPlan, parent_job_id: str)
    │
    ├── 1. Split plan.subtasks into "ready" (empty depends_on) and "blocked"
    ├── 2. For each subtask spec, build a SubTaskJob envelope
    ├── 3. Enqueue all SubTaskJobs via S4 Queue API
    ├── 4. Create JoinHandle referencing all child job IDs
    ├── 5. Persist JoinHandle in S4 Join Store
    ├── 6. Submit ContinuationJob (blocked until JoinHandle completes)
    └── 7. Return FanOutResult(job_ids=[...], join_handle_id=...)
```

### 5.2 Child Job Envelope

```python
@dataclass(frozen=True)
class SubTaskJob(JobEnvelope):
    """Child job for a single subtask in a decomposition DAG."""
    # Inherited from JobEnvelope:
    #   job_id: str
    #   job_type: str = "subtask"
    #   parent_job_id: str
    #   priority: int
    #   created_at: float
    #   max_retries: int
    #   timeout_seconds: int
    
    # SubTaskJob-specific fields:
    plan_id: str                         # Links to the parent DecompositionPlan
    subtask_id: str                      # Matches SubtaskSpec.id
    subtask_description: str             # Atomic action description
    target_agent_id: str | None          # Agent to route execution to
    target_skill_id: str | None          # Skill override
    arguments: dict[str, Any]            # Input arguments for the subtask
    depends_on: list[str]                # Subtask IDs this job depends on (from DAG)
    parent_result_context: str | None    # Optional: parent context snapshot
    
    # Serialized into job payload for queue persistence
```

### 5.3 Enqueue Operation

```python
def enqueue_child_jobs(
    plan: DecompositionPlan,
    parent_job_id: str,
    queue_api: QueueAPI,
) -> list[str]:
    """Enqueue one job per subtask. Returns list of child job IDs."""
    child_job_ids: list[str] = []
    
    for subtask in plan.subtasks:
        job = SubTaskJob(
            job_id=generate_job_id(),           # S4 idempotent ID generation
            job_type="subtask",
            parent_job_id=parent_job_id,
            priority=subtask.priority,
            max_retries=subtask.max_retries,
            timeout_seconds=subtask.timeout_seconds,
            plan_id=plan.plan_id,
            subtask_id=subtask.id,
            subtask_description=subtask.description,
            target_agent_id=subtask.target_agent_id,
            target_skill_id=subtask.target_skill_id,
            arguments=subtask.arguments,
            depends_on=subtask.depends_on,
            parent_result_context=None,
        )
        job_id = queue_api.enqueue(job)
        child_job_ids.append(job_id)
    
    return child_job_ids
```

### 5.4 Dependency Metadata Attachment

Dependencies are encoded in two places:
1. **Job envelope** (`SubTaskJob.depends_on`): declarative, for scheduling decisions.
2. **JoinHandle** (`JoinHandle.dependency_map`): operational, for tracking satisfaction.

The S4 Scheduler reads `depends_on` to decide readiness. The JoinHandle tracks completion and propagates state.

---

## 6. Join‑Handle Design

### 6.1 Schema

```python
@dataclass
class JoinHandle:
    """Tracks fan-out completion for a decomposition plan."""
    # Identity
    join_handle_id: str                        # Unique handle ID
    plan_id: str                               # Links to DecompositionPlan
    parent_job_id: str                         # The job that initiated fan-out
    
    # Child tracking
    child_job_ids: list[str]                   # All child job IDs
    dependency_map: dict[str, list[str]]       # subtask_id → [dep_subtask_ids, ...]
    
    # Completion tracking (maps subtask_id → completion status)
    completed: dict[str, bool]                 # subtask_id → completed?
    results: dict[str, JobResult]              # subtask_id → result (populated on completion)
    
    # State
    state: str                                 # "OPEN" | "PARTIAL" | "READY" | "DONE" | "FAILED" | "TIMED_OUT"
    total_children: int                        # len(child_job_ids)
    completed_count: int                       # Count of completed children
    failed_count: int                          # Count of failed children
    
    # Timestamps
    created_at: float
    completed_at: float | None
    timeout_seconds: int                       # Global join timeout
```

### 6.2 State Transitions

```
OPEN ──→ PARTIAL ──→ READY ──→ DONE
  │         │                    ▲
  │         └──→ FAILED ─────────┘
  │         └──→ TIMED_OUT ──────┘
  └──→ TIMED_OUT (if timeout expires with 0 completions)
```

| State | Meaning | Trigger |
|-------|---------|---------|
| `OPEN` | No children have completed yet | Created at fan-out |
| `PARTIAL` | Some children completed, some pending | First child result arrives |
| `READY` | All children completed (success or fail) | Last child result arrives; all deps satisfied |
| `DONE` | ContinuationJob picked up the results | ContinuationJob dequeued the handle |
| `FAILED` | A child with `critical=true` failed, or all children failed | Child failure with critical flag |
| `TIMED_OUT` | Global timeout expired before all children finished | Clock exceeds `timeout_seconds` |

### 6.3 Child Job Completion Reporting

When a worker completes a `SubTaskJob`, it calls:

```python
def report_completion(
    join_store: JoinStore,
    join_handle_id: str,
    subtask_id: str,
    result: JobResult,
) -> JoinHandle:
    """Route: Worker → S4 Control Plane → JoinStore."""
    handle = join_store.get(join_handle_id)
    handle.completed[subtask_id] = True
    handle.results[subtask_id] = result
    handle.completed_count = sum(1 for v in handle.completed.values() if v)
    
    if result.status == "FAILED":
        handle.failed_count += 1
    
    # State evaluation
    if handle.completed_count == handle.total_children:
        handle.state = "READY"
        handle.completed_at = time.time()
        # Signal: drain any blocked ContinuationJob
        join_store.signal_ready(handle.join_handle_id)
    else:
        handle.state = "PARTIAL"
    
    return join_store.update(handle)
```

### 6.4 "All Children Complete" Detection

S4 Control Plane detects "all children complete" by:
1. **Polling**: The ContinuationJob polls `JoinStore.get(join_handle_id)` every `poll_interval_ms` (default: 500ms) until `state ∈ {READY, FAILED, TIMED_OUT}`.
2. **Signal**: When `JoinStore` transitions a handle to `READY`, it emits an internal event. The Scheduler drains blocked jobs that are waiting on that handle.

Implementation preference: **signal over polling**. The S4 Scheduler already supports blocking dequeue conditions (used by agent deferral). This is extended with a `BLOCKED_ON_JOIN` condition.

### 6.5 Dependency Satisfaction Tracking

The S4 Scheduler evaluates dependency satisfaction for each pending child job:

```python
def is_dependency_satisfied(
    subtask_id: str,
    job: SubTaskJob,
    handle: JoinHandle,
) -> bool:
    """A subtask's dependencies are satisfied when all depends_on subtasks are complete."""
    for dep_id in job.depends_on:
        if not handle.completed.get(dep_id, False):
            return False
    return True
```

Jobs with empty `depends_on` are **immediately ready** and released to workers on enqueue.

---

## 7. Dependency‑Aware Scheduling

### 7.1 When a Job Is "Ready"

A `SubTaskJob` is ready when:
1. It is in the queue with status `PENDING`.
2. All subtasks listed in `job.depends_on` have `completed=True` in the corresponding `JoinHandle`.

### 7.2 Blocking Jobs Until Dependencies Complete

```python
# S4 Scheduler: per-queue dispatch loop
def dispatch_loop(queue: Queue, join_store: JoinStore):
    for job in queue.peek_pending():
        if job.job_type != "subtask":
            yield job  # Non-subtask jobs: dispatch immediately
            continue
        
        handle = join_store.get_by_plan_id(job.plan_id)
        if handle is None:
            continue  # Handle not yet created; skip
        
        if is_dependency_satisfied(job.subtask_id, job, handle):
            yield job  # Ready to dispatch
        # else: skip — job remains PENDING, will be re-evaluated next poll
```

### 7.3 Enqueuing Ready Jobs

Jobs are enqueued at fan-out time regardless of dependency status. The Scheduler holds blocked jobs in PENDING state. When a child job completes and the JoinStore updates, the Scheduler re-scans blocked jobs for newly satisfied dependencies.

```
Worker completes subtask-0
    │
    ├── JoinStore.handle.completed["subtask-0"] = True
    │
    ├── Scheduler re-evaluates blocked jobs for this plan
    │       │
    │       ├── subtask-1: depends_on=["subtask-0"] → NOW READY → dispatch
    │       └── subtask-2: depends_on=["subtask-0"] → NOW READY → dispatch
    │
    └── subtask-3: depends_on=["subtask-1", "subtask-2"] → STILL BLOCKED
```

Re-evaluation is triggered by the join store update, not by polling. This is O(N) per completion where N = number of blocked jobs for the plan (typically small, ≤ max_children).

### 7.4 Max Concurrency Per Plan

```python
# Config
MAX_CONCURRENT_CHILDREN_PER_PLAN = 8   # Default: matches max_children
MAX_TOTAL_CONCURRENT_CHILDREN = 64     # Across all plans
```

The Scheduler respects these limits. If a plan has 20 subtasks but `MAX_CONCURRENT_CHILDREN_PER_PLAN=8`, at most 8 run at once. The remaining 12 stay PENDING until slots free. This is a safeguard against resource exhaustion, not a correctness constraint.

---

## 8. Continuation Job

### 8.1 What the Continuation Job Is

The ContinuationJob is a special S4 job that blocks until the JoinHandle reaches `READY`, then wakes up and invokes the parent agent's merge logic.

```python
@dataclass(frozen=True)
class ContinuationJob(JobEnvelope):
    """Job that resumes parent agent after all children complete."""
    # Inherited: job_id, job_type="continuation", parent_job_id, etc.
    plan_id: str                           # Links to DecompositionPlan
    join_handle_id: str                    # Block until this handle is READY
    merge_strategy: str                    # From plan.merge_strategy
    merge_agent_id: str                    # Agent to execute merge
    merge_prompt_template: str | None      # LLM prompt for summarize_llm merge
    parent_snapshot_ref: str               # Reference to parent agent's suspended state
```

### 8.2 Lifecycle

```
Fan-out complete
    │
    ├── ContinuationJob enqueued with state=BLOCKED
    │
    ├── Scheduler: job is BLOCKED_ON_JOIN(join_handle_id)
    │       │
    │       └── ... children execute, complete ...
    │
    ├── JoinHandle → READY
    │       │
    │       └── Scheduler: unblock ContinuationJob
    │
    ├── Worker picks up ContinuationJob
    │       │
    │       ├── Load parent_snapshot_ref → restore agent context
    │       ├── Load child results from JoinHandle
    │       ├── Execute merge_strategy
    │       ├── Persist merged result
    │       └── Mark plan COMPLETE
    │
    └── Parent agent receives merged result, resumes Agent Loop
```

### 8.3 Passing Child Results to Parent

Child results are stored in `JoinHandle.results` (dict[str, JobResult]). The ContinuationJob worker:

```python
def execute_continuation(job: ContinuationJob, join_store: JoinStore):
    handle = join_store.get(job.join_handle_id)
    
    # Extract child results
    child_results: dict[str, JobResult] = handle.results
    
    # Restore parent agent context
    parent_context = snapshot_store.load(job.parent_snapshot_ref)
    
    # Execute merge (see Section 9)
    merged_result = execute_merge(
        strategy=job.merge_strategy,
        child_results=child_results,
        prompt_template=job.merge_prompt_template,
        parent_context=parent_context,
    )
    
    # Store merged result back to parent agent's context
    parent_context.decomposition_result = merged_result
    
    # Mark handle DONE
    handle.state = "DONE"
    join_store.update(handle)
    
    # Signal parent agent loop to resume
    signal_agent_resume(job.parent_job_id, merged_result)
```

---

## 9. Fan‑In Merge Logic

### 9.1 Merge Strategies

| Strategy | Description | When to Use |
|----------|-------------|-------------|
| `concat` | Concatenate results in DAG topological order. No LLM call. | Homogeneous results (e.g., list of linting errors) |
| `summarize_llm` | Pass all results through LLM with a merge prompt template. | Heterogeneous results needing synthesis |
| `select_best` | Apply a scoring function to each result; keep the top-ranked. | Multiple attempts at same task (speculative execution) |
| `custom` | Invoke a registered merge function by name from `plan.metadata["custom_merge_fn"]`. | Specialized merge logic |

### 9.2 Merge Execution

```python
def execute_merge(
    strategy: str,
    child_results: dict[str, JobResult],
    prompt_template: str | None,
    parent_context: AgentContext,
) -> MergeResult:
    """Fan-in: combine N child results into one merged output."""
    
    if strategy == "concat":
        # Deterministic: sort by topological order, join results
        sorted_results = topological_sort(child_results)
        combined = "\n\n".join(
            f"## {subtask_id}\n{r.output}"
            for subtask_id, r in sorted_results
        )
        return MergeResult(output=combined, strategy=strategy)
    
    elif strategy == "summarize_llm":
        # LLM-based synthesis
        formatted_children = format_child_results(child_results)
        prompt = prompt_template.format(
            parent_task=parent_context.task,
            child_results=formatted_children,
        )
        llm_output = llm_call(
            agent_id=parent_context.agent_id,
            system_prompt="You are a merge agent. Synthesize child task results into a coherent final output.",
            user_prompt=prompt,
        )
        return MergeResult(output=llm_output, strategy=strategy)
    
    elif strategy == "select_best":
        # Score-based selection
        scoring_fn = parent_context.scoring_function
        best = max(
            child_results.values(),
            key=lambda r: scoring_fn(r.output),
        )
        return MergeResult(output=best.output, strategy=strategy, selected=best.subtask_id)
    
    elif strategy == "custom":
        # Plugin merge function
        fn_name = parent_context.custom_merge_fn
        merge_fn = merge_registry.get(fn_name)
        return merge_fn(child_results, parent_context)
```

### 9.3 Maintaining the North Star

The "North Star" is the parent task's original goal. Every merge strategy must:
1. Accept the parent task description as context.
2. Evaluate whether the merged result satisfies the parent task's acceptance criteria.
3. If not satisfied, append a `satisfaction_gap` field to `MergeResult` so the parent agent can decide: re-decompose, retry children, or report partial success.

```python
@dataclass(frozen=True)
class MergeResult:
    output: str
    strategy: str
    selected: str | None = None            # For select_best
    satisfaction_gap: str | None = None    # If merge doesn't fully satisfy parent task
    child_summaries: dict[str, str] = field(default_factory=dict)  # subtask_id → summary
```

### 9.4 Handling Partial Failures in Merge

If some children failed but the merge strategy can proceed with partial results:

```python
def execute_merge_with_partials(
    strategy: str,
    child_results: dict[str, JobResult],
    handle: JoinHandle,
    parent_context: AgentContext,
) -> MergeResult:
    """Merge allowing partial failures where strategy permits."""
    
    succeeded = {k: v for k, v in child_results.items() if v.status == "SUCCESS"}
    failed = {k: v for k, v in child_results.items() if v.status == "FAILED"}
    
    if not succeeded and strategy != "select_best":
        # Total failure — cannot merge
        return MergeResult(
            output=f"All {len(failed)} children failed.",
            strategy=strategy,
            satisfaction_gap="Total child failure. Cannot produce merged result.",
            child_summaries={k: f"FAILED: {v.error}" for k, v in failed.items()},
        )
    
    # Merge from succeeded children only
    return execute_merge(strategy, succeeded, parent_context.prompt_template, parent_context)
```

---

## 10. Failure Handling

### 10.1 Retry Strategy

Each `SubTaskJob` carries its own `max_retries`. Retries are handled by the S4 job system — the orchestrator does not implement its own retry loop.

| Failure Type | Retry Behavior |
|--------------|---------------|
| Transient (network, timeout) | S4 retries up to `max_retries` with exponential backoff (1s, 2s, 4s, ...) |
| Permanent (validation error, not found) | No retry. Job transitions to FAILED immediately. |
| Dependency failure | If subtask A fails and subtask B depends on A, B is automatically FAILED with reason "DEPENDENCY_FAILED" |

### 10.2 Partial Failure Propagation

```python
def propagate_dependency_failures(handle: JoinHandle, job_store: JobStore):
    """When a job fails, fail all transitive dependents."""
    for subtask_id, failed in handle.failed_subtasks():
        if not failed:
            continue
        # Find all jobs that depend (directly or transitively) on the failed subtask
        dependents = find_transitive_dependents(subtask_id, handle.dependency_map)
        for dep_id in dependents:
            if not handle.completed[dep_id]:
                job = job_store.get_by_subtask_id(handle.plan_id, dep_id)
                job_store.fail_job(
                    job.job_id,
                    reason=f"Dependency failed: {subtask_id}",
                    error_code="DEPENDENCY_FAILED",
                )
                handle.completed[dep_id] = True
                handle.failed_count += 1
```

### 10.3 Timeout Handling

Two levels of timeout:

| Level | Scope | Default | Behavior on Expiry |
|-------|-------|---------|---------------------|
| Per-subtask | Individual `SubTaskJob` | 300s | Job fails. S4 retries if retries remain. Then treated as permanent failure. |
| Per-plan (JoinHandle) | Entire decomposition | 1800s | `JoinHandle` → `TIMED_OUT`. All pending children cancelled. ContinuationJob unblocks with partial results. |

### 10.4 Failure Decision Matrix

| Scenario | Behavior |
|----------|----------|
| One child fails, no dependents | Other children continue. Merge proceeds with partial results. |
| One child fails, dependents exist | Dependents immediately fail with `DEPENDENCY_FAILED`. Merge proceeds with remaining results. |
| All children fail | `JoinHandle` → `FAILED`. ContinuationJob unblocks. Merge returns total-failure result. Parent agent decides next step. |
| Plan timeout | `JoinHandle` → `TIMED_OUT`. Pending children cancelled. Merge from completed children only. |
| ContinuationJob fails | S4 retries ContinuationJob (it is idempotent — reads from JoinStore, not re-executes children). |
| Parent agent cancelled | Cascade-cancel all pending child jobs. Fail the `JoinHandle`. |

### 10.5 Circuit Breaker

To prevent runaway decomposition:

```python
# Config
CIRCUIT_BREAKER_MAX_DEPTH = 3             # Max nesting depth of decomposition
CIRCUIT_BREAKER_MAX_TOTAL_JOBS = 100      # Max total jobs per root decomposition
CIRCUIT_BREAKER_WINDOW_SECONDS = 300      # Time window for rate limiting
CIRCUIT_BREAKER_MAX_PLANS_PER_WINDOW = 10 # Max decomposition plans per window
```

If a subtask is itself non-atomic and triggers further decomposition, depth is checked. If `current_depth >= CIRCUIT_BREAKER_MAX_DEPTH`, the subtask is executed atomically (best-effort) instead of being further decomposed.

---

## 11. End‑to‑End Example

### 11.1 Scenario

**Parent task:** "Audit repository X for security vulnerabilities, fix all high-severity issues, and generate a compliance report."

### 11.2 Step 1: Atomicity Test

```
Task: "Audit repository X for security vulnerabilities, fix all high-severity issues, and generate a compliance report."

One action?      NO — audit + fix + report = 3+ actions
One deliverable? NO — audit results + fixed code + report = 3+ deliverables
One acceptance?  NO — audit complete AND fixes applied AND report generated

→ NON-ATOMIC → Decomposition triggered
```

### 11.3 Step 2: Planner Output (DecompositionPlan)

```json
{
  "plan_id": "plan-audit-001",
  "parent_task": "Audit repository X for security vulnerabilities, fix all high-severity issues, and generate a compliance report.",
  "merge_strategy": "summarize_llm",
  "merge_agent_id": "security-auditor",
  "merge_prompt_template": "Synthesize the following security audit results, fixes applied, and report into a final compliance summary:\n\n{child_results}",
  "subtasks": [
    {
      "id": "subtask-0",
      "description": "Clone repository X and perform static security scan using Bandit/Semgrep",
      "target_agent_id": "security-scanner",
      "depends_on": [],
      "priority": 10
    },
    {
      "id": "subtask-1",
      "description": "Classify each vulnerability by severity (Critical/High/Medium/Low) and CWE category",
      "target_agent_id": "vulnerability-classifier",
      "depends_on": ["subtask-0"],
      "priority": 5
    },
    {
      "id": "subtask-2",
      "description": "Fix all high-severity and critical vulnerabilities in the codebase",
      "target_agent_id": "code-fixer",
      "depends_on": ["subtask-1"],
      "priority": 8
    },
    {
      "id": "subtask-3",
      "description": "Generate compliance report in SOC2 format from audit results and fix summary",
      "target_agent_id": "report-generator",
      "depends_on": ["subtask-1", "subtask-2"],
      "priority": 3
    }
  ]
}
```

### 11.4 DAG Visualization

```
              subtask-0
          (security scan)
                  │
                  ▼
              subtask-1
         (vulnerability classification)
             │         │
        ┌────┘         └────┐
        ▼                   ▼
    subtask-2           subtask-3
   (fix issues)    (compliance report)
        │                   ▲
        └───────────────────┘
          (subtask-3 depends
           on both 1 and 2)
```

### 11.5 Step 3: Fan-Out

```
DecompositionOrchestrator.fan_out():
    subtask-0 → enqueue job-job-0 (priority=10, depends_on=[])
    subtask-1 → enqueue job-job-1 (priority=5,  depends_on=["subtask-0"])
    subtask-2 → enqueue job-job-2 (priority=8,  depends_on=["subtask-1"])
    subtask-3 → enqueue job-job-3 (priority=3,  depends_on=["subtask-1", "subtask-2"])
    
    JoinHandle created: join-abc123 (4 children, state=OPEN)
    ContinuationJob enqueued: job-cont-001 (BLOCKED_ON_JOIN: join-abc123)
```

### 11.6 Step 4: Dependency‑Aware Execution

```
T=0s    Scheduler: job-0 ready (empty depends_on) → dispatch to Worker-1
        jobs 1,2,3 blocked

T=45s   Worker-1 completes job-0 (scan results: 12 vulnerabilities found)
        JoinStore: handle.completed["subtask-0"] = True, state=PARTIAL
        
        Scheduler re-evaluates:
            job-1: depends_on=["subtask-0"] → READY → dispatch to Worker-2
            job-2: depends_on=["subtask-1"] → BLOCKED
            job-3: depends_on=["subtask-1","subtask-2"] → BLOCKED

T=60s   Worker-2 completes job-1 (classification: 2 Critical, 5 High, 3 Medium, 2 Low)
        JoinStore: handle.completed["subtask-1"] = True, state=PARTIAL
        
        Scheduler re-evaluates:
            job-2: depends_on=["subtask-1"] → READY → dispatch to Worker-3
            job-3: depends_on=["subtask-1","subtask-2"] → BLOCKED (job-2 not yet done)

T=150s  Worker-3 completes job-2 (fixes applied: 7 patches committed)
        JoinStore: handle.completed["subtask-2"] = True, state=PARTIAL
        
        Scheduler re-evaluates:
            job-3: depends_on=["subtask-1","subtask-2"] → READY → dispatch to Worker-4

T=180s  Worker-4 completes job-3 (compliance report generated)
        JoinStore: ALL completed → state=READY
```

### 11.7 Step 5: Fan‑In (Merge)

```
JoinHandle → READY
    │
    ├── Scheduler unblocks ContinuationJob (job-cont-001)
    │
    ├── Worker-5 picks up job-cont-001
    │       │
    │       ├── Load child results from JoinHandle:
    │       │       subtask-0: "12 vulnerabilities found: ..."
    │       │       subtask-1: "Classification: 2 Crit, 5 High, ..."
    │       │       subtask-2: "Fixed: 7 patches applied to ..."
    │       │       subtask-3: "SOC2 Report: ..."
    │       │
    │       ├── Execute merge_strategy="summarize_llm":
    │       │       LLM prompt = merge_prompt_template.format(
    │       │           child_results=formatted_results
    │       │       )
    │       │
    │       ├── LLM output: "Security audit complete. Found and classified
    │       │       12 vulnerabilities. All 7 high/critical issues fixed.
    │       │       SOC2 compliance report generated. Summary: ..."
    │       │
    │       └── MergeResult stored, parent agent signalled
    │
    └── Parent agent resumes: processes MergeResult, continues Agent Loop
```

### 11.8 Step 6: Parent Agent Resumption

```
S5 Agent Loop resumes
    │
    ├── agent.state = ACTIVE (was AWAITING_CHILDREN)
    ├── agent.context.decomposition_result = MergeResult(...)
    ├── Agent evaluates: does merged result satisfy parent task?
    │       │
    │       ├── YES → incorporate into working memory, proceed to next task
    │       └── NO  → check satisfaction_gap; decide re-decompose or report
    │
    └── Agent Loop continues
```

### 11.9 Failure Example

Same plan, but `subtask-0` (security scan) fails after exhausting retries:

```
T=0s    job-0 dispatched, fails repeatedly, max_retries exhausted
T=120s  job-0 → FAILED (permanent)
        propagate_dependency_failures():
            dependents of subtask-0: [subtask-1, subtask-2, subtask-3]
            All are failed with DEPENDENCY_FAILED
            
        JoinHandle: all 4 complete (1 FAILED, 3 DEPENDENCY_FAILED)
        JoinHandle → FAILED
        ContinuationJob unblocks
        
        Merge: all children failed → total failure
        MergeResult.satisfaction_gap = "Total child failure..."
        
        Parent agent resumes, receives total-failure MergeResult
        Parent agent reports: "Security audit cannot proceed: scan tool failed."
```

---

*End of roadmap.*

---

## Appendix A: Concrete Codebase Mapping

This appendix maps every abstract concept in the roadmap to the actual codebase. Use this as the implementation reference — the roadmap describes *what* to build; this appendix describes *where* and *how*.

### A.1 Job Model — Extending `Job` Instead of `JobEnvelope`

The roadmap references a `JobEnvelope` base class. **This does not exist.** The real base is `Job`:

**File:** `src/platform/runtime/job.py`

```python
class Job(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state: JobState = JobState.PENDING
    payload: ChannelMessage
    result: dict[str, Any] | None = None
    trace: list[dict] = Field(default_factory=list)
    execution_context: ExecutionContext | None = None
    resume_token: str | None = None
    failure_count: int = 0
    consecutive_failures: int = 0
    panic_count: int = 0
    crash_count: int = 0
```

**Implementation plan — extend Job with these new fields:**

Add to `Job`:
```python
    job_type: str = "default"                    # "subtask" | "continuation" | "default"
    parent_job_id: str | None = None             # Links child → parent
    priority: int = 0                            # Higher = earlier dispatch
    max_retries: int = 0                         # Per-job retry limit
    timeout_seconds: int = 300                   # Per-job timeout
    plan_id: str | None = None                   # Links to DecompositionPlan
    subtask_id: str | None = None                # Matches SubtaskSpec.id
    depends_on: list[str] = Field(default_factory=list)  # Subtask IDs this job waits for
```

**File:** `src/platform/runtime/job_state.py`

Add to `JobState`:
```python
    BLOCKED = "blocked"     # Waiting on join handle or dependencies
```

Add to `_TRANSITIONS`:
```python
    (JobState.PENDING, JobState.BLOCKED),
    (JobState.BLOCKED, JobState.PENDING),   # Unblocked when deps satisfied
    (JobState.BLOCKED, JobState.FAILED),    # Dependency failure propagation
```

### A.2 Queue API — Using `Queue.push()` Not `QueueAPI.enqueue()`

The roadmap uses `queue_api.enqueue()`. The real API is:

**File:** `src/platform/queue/queue.py`

```python
class Queue(ABC):
    def push(self, item: dict) -> None: ...
    def pop(self, timeout: float = 0) -> dict | None: ...
    def acknowledge(self, item: dict) -> None: ...
    def requeue(self, item: dict) -> None: ...
    def nack(self, item: dict, reason: str = "") -> None: ...
    def __len__(self) -> int: ...
```

**Implementation plan:** When the roadmap says `queue_api.enqueue(job)`, call `queue.push(job.model_dump())`. When the roadmap says `dequeue`, call `queue.pop()`. Wrap jobs in dicts for queue storage — the queue stores `dict`, not `Job` objects.

### A.3 Agent Lifecycle — Adding `AWAITING_CHILDREN`

**File:** `src/agent/interfaces/agent_state.py`

Add to `LifecycleState`:
```python
    AWAITING_CHILDREN = "awaiting_children"   # Parent suspended during fan-out
```

This is NOT terminal; transition rules:
```
RUNNING → AWAITING_CHILDREN  (when fan-out starts)
AWAITING_CHILDREN → RUNNING  (when fan-in merge completes)
AWAITING_CHILDREN → FAILED   (if decomposition fails irrecoverably)
```

Add `is_active()` check: `AWAITING_CHILDREN` is NOT active (parent is suspended).

Update `AgentState.with_()` to handle the new state — add a `decomposition_result` field:
```python
    decomposition_result: dict[str, Any] | None = None
```

### A.4 S2 Planner — Adding `S2PlanDecomposer` Protocol

**File:** `src/agent/interfaces/s2_planner.py` (extend this file)

The existing protocol:
```python
class S2Planner(Protocol):
    def plan(self, goal: str, subgoal_id: str, governance: MemoryGovernance,
             capabilities: Optional[List[DiscoveredSkill]] = None) -> Plan: ...
```

**Add a new protocol in the same file:**
```python
@runtime_checkable
class S2PlanDecomposer(Protocol):
    """S5 → S2: Decompose a non-atomic task into a dependency DAG."""

    def decompose(self, request: DecompositionRequest) -> DecompositionPlan:
        """Analyse a non-atomic task and produce a decomposition DAG.
        
        Args:
            request: Contains parent_task, parent_context, available_agents,
                     and constraints.
        
        Returns:
            A DecompositionPlan with validated, acyclic subtask DAG.
        """
        ...
```

### A.5 New Types — Where to Create Each File

All new types follow the existing convention: `dataclass` or `BaseModel` in `src/agent/types/` or `src/platform/runtime/`.

| Type | File to Create | Base Class |
|------|---------------|------------|
| `DecompositionRequest` | `src/agent/types/decomposition.py` | `dataclass` (frozen) |
| `SubtaskSpec` | `src/agent/types/decomposition.py` | `dataclass` (frozen) |
| `DecompositionPlan` | `src/agent/types/decomposition.py` | `dataclass` (frozen) |
| `MergeResult` | `src/agent/types/decomposition.py` | `dataclass` (frozen) |
| `JoinHandle` | `src/platform/runtime/join_handle.py` | `BaseModel` |

**Complete schema for `src/agent/types/decomposition.py`:**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecompositionRequest:
    """Input to S2PlanDecomposer.decompose(). Pure data, no I/O."""
    parent_task: str
    parent_context: dict[str, Any]             # Memory snapshot from agent
    available_agents: list[str]                 # Agent IDs from registry
    constraints: dict[str, int] = field(default_factory=lambda: {
        "max_depth": 2,
        "max_children": 8,
    })


@dataclass(frozen=True)
class SubtaskSpec:
    """A single atomic subtask in a decomposition DAG."""
    id: str
    description: str
    target_agent_id: str | None = None
    target_skill_id: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    priority: int = 0
    timeout_seconds: int = 300
    max_retries: int = 2


@dataclass(frozen=True)
class DecompositionPlan:
    """Output of S2PlanDecomposer.decompose(). Pure data, no I/O."""
    plan_id: str
    parent_task: str
    subtasks: list[SubtaskSpec]
    merge_strategy: str                        # "concat" | "summarize_llm" | "select_best" | "custom"
    merge_agent_id: str | None = None
    merge_prompt_template: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MergeResult:
    """Result of fan-in merge. Stored in parent agent's supervisor_metadata."""
    output: str
    strategy: str
    selected: str | None = None
    satisfaction_gap: str | None = None
    child_summaries: dict[str, str] = field(default_factory=dict)
```

### A.6 Join Store — Following the Store Pattern

Existing store pattern (from `src/platform/runtime/stores/`):

```python
# src/platform/runtime/stores/job_store.py  (abstract)
class JobStore(ABC):
    def save(self, job: Job) -> None: ...
    def get(self, job_id: str) -> Job | None: ...
    def list_jobs(self, state: JobState | None = None) -> list[Job]: ...
    def delete(self, job_id: str) -> None: ...
```

**Create:** `src/platform/runtime/stores/join_store.py`

```python
from abc import ABC, abstractmethod
from src.platform.runtime.join_handle import JoinHandle


class JoinStore(ABC):
    """Tracks fan-out completion for decomposition plans."""

    @abstractmethod
    def create(self, handle: JoinHandle) -> None:
        """Persist a new JoinHandle."""
        ...

    @abstractmethod
    def get(self, join_handle_id: str) -> JoinHandle | None:
        """Retrieve by handle ID."""
        ...

    @abstractmethod
    def get_by_plan_id(self, plan_id: str) -> JoinHandle | None:
        """Retrieve by decomposition plan ID."""
        ...

    @abstractmethod
    def update(self, handle: JoinHandle) -> JoinHandle:
        """Update an existing handle. Returns the persisted copy."""
        ...

    @abstractmethod
    def signal_ready(self, join_handle_id: str) -> None:
        """Signal that the handle is READY — unblocks ContinuationJob."""
        ...
```

**Also create:** `src/platform/runtime/stores/in_memory_join_store.py` as the default in-memory implementation, following the pattern of `InMemoryJobStore`.

### A.7 DecompositionOrchestrator — Following the Deferral Pattern

The deferral resolver pattern:

```
src/agent/deferral/
├── __init__.py          # Public API exports
├── resolver.py          # DeferralResolver class
├── depth_guard.py       # DepthGuard
├── context_bridge.py    # ContextBridge
└── validator.py         # validate_deferral_graph()
```

**Create:** `src/agent/decomposition/` following the same conventions:

```
src/agent/decomposition/
├── __init__.py              # Public API exports
├── orchestrator.py          # DecompositionOrchestrator class
├── dag_validator.py         # validate_dag() function
├── fan_out.py               # enqueue_child_jobs() function
└── fan_in.py                # execute_merge() function
```

**`DecompositionOrchestrator` class (in `orchestrator.py`):**

```python
class DecompositionOrchestrator:
    """Coordinates decomposition, fan-out, and fan-in for non-atomic tasks."""

    def __init__(self, planner: S2PlanDecomposer, queue: Queue,
                 join_store: JoinStore, job_store: JobStore,
                 registry: AgentRegistry) -> None: ...

    def decompose(self, task: str, parent_state: AgentState,
                  parent_job_id: str) -> FanOutResult:
        """1. Test atomicity → 2. Call planner → 3. Validate DAG →
           4. Fan-out → 5. Create JoinHandle → 6. Submit ContinuationJob"""
        ...

    def fan_out(self, plan: DecompositionPlan, parent_job_id: str) -> FanOutResult: ...
    
    def fan_in(self, join_handle_id: str, parent_state: AgentState) -> MergeResult: ...
```

**`FanOutResult` dataclass:**
```python
@dataclass(frozen=True)
class FanOutResult:
    child_job_ids: list[str]
    join_handle_id: str
    continuation_job_id: str
```

### A.8 Atomicity Test — Concrete Implementation

The atomicity test can be implemented as an LLM call or a heuristic. For deterministic behavior matching the roadmap:

**Create:** `src/agent/decomposition/atomicity.py`

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class AtomicityResult:
    is_atomic: bool
    reason: str                      # Explanation for non-atomic case

def test_atomicity(task: str) -> AtomicityResult:
    """Determine if a task is atomic (one action, one deliverable, one acceptance criterion).
    
    Uses a lightweight LLM call with a structured prompt. Falls back to
    heuristics (conjunction count, verb count) if LLM is unavailable.
    """
    ...
```

### A.9 Supervisor Integration — Adding `decompose_task()` Method

**File:** `src/agent/supervisor.py`

Follow the exact same pattern as `defer_to_agent()` (line 1206):

```python
def decompose_task(
    self,
    state: AgentState,
    task: str,
    *,
    max_depth: int = 2,
) -> AgentState:
    """Fan-out a non-atomic task to N child agents, wait, then merge results.
    
    Full lifecycle: suspend parent (AWAITING_CHILDREN) → fan-out N child
    jobs → wait for JoinHandle → fan-in merge → resume parent (RUNNING).
    
    The parent must be in RUNNING or WAITING state.
    After this call the parent is in RUNNING state with merged results
    in ``supervisor_metadata["decomposition_result"]``.
    """
    ...
```

### A.10 Config Keys — Adding to SCHEMA

**File:** `src/config/config_system.py`

Add a `"decomposition"` section to the `SCHEMA` dict:

```python
    "decomposition": {
        "type": dict,
        "fields": {
            "max_depth": {"type": int, "default": 2},
            "max_children": {"type": int, "default": 8},
            "max_concurrent_children_per_plan": {"type": int, "default": 8},
            "max_total_concurrent_children": {"type": int, "default": 64},
            "plan_timeout_seconds": {"type": int, "default": 1800},
            "subtask_timeout_seconds": {"type": int, "default": 300},
            "circuit_breaker_max_depth": {"type": int, "default": 3},
            "circuit_breaker_max_total_jobs": {"type": int, "default": 100},
            "circuit_breaker_window_seconds": {"type": int, "default": 300},
            "circuit_breaker_max_plans_per_window": {"type": int, "default": 10},
        },
    },
```

Accessible as `config.get("decomposition.max_depth")` or via env var `S4_DECOMPOSITIONMAX_DEPTH=3`.

### A.11 Scheduler Changes — Adding BLOCKED_ON_JOIN

**Implementation plan for S4 Scheduler:** (file TBD — find existing scheduler)

1. When dispatching, check if job has `depends_on` list with unsatisfied dependencies → set `state = BLOCKED` instead of dispatching.
2. When a `SubTaskJob` completes, update the `JoinHandle` in `JoinStore`.
3. After join store update, re-scan all `BLOCKED` jobs for the same `plan_id`.
4. For each blocked job where `is_dependency_satisfied()` returns True, transition `BLOCKED → PENDING` and dispatch.
5. When a job fails, call `propagate_dependency_failures()` to fail transitive dependents.

### A.12 Complete File Creation/Modification Checklist

| # | Action | File | Type |
|---|--------|------|------|
| 1 | **Modify** — add fields | `src/platform/runtime/job.py` | Add `job_type`, `parent_job_id`, `priority`, `max_retries`, `timeout_seconds`, `plan_id`, `subtask_id`, `depends_on` |
| 2 | **Modify** — add BLOCKED state | `src/platform/runtime/job_state.py` | Add `BLOCKED = "blocked"` and transitions |
| 3 | **Modify** — add AWAITING_CHILDREN | `src/agent/interfaces/agent_state.py` | Add `AWAITING_CHILDREN` to `LifecycleState` |
| 4 | **Modify** — add decompose protocol | `src/agent/interfaces/s2_planner.py` | Add `S2PlanDecomposer` protocol |
| 5 | **Modify** — add config section | `src/config/config_system.py` | Add `"decomposition"` section to `SCHEMA` |
| 6 | **Create** — types | `src/agent/types/decomposition.py` | `DecompositionRequest`, `SubtaskSpec`, `DecompositionPlan`, `MergeResult` |
| 7 | **Create** — join handle | `src/platform/runtime/join_handle.py` | `JoinHandle` BaseModel |
| 8 | **Create** — join store interface | `src/platform/runtime/stores/join_store.py` | `JoinStore` ABC |
| 9 | **Create** — in-memory join store | `src/platform/runtime/stores/in_memory_join_store.py` | `InMemoryJoinStore` |
| 10 | **Create** — orchestrator | `src/agent/decomposition/orchestrator.py` | `DecompositionOrchestrator`, `FanOutResult` |
| 11 | **Create** — DAG validator | `src/agent/decomposition/dag_validator.py` | `validate_dag()` |
| 12 | **Create** — fan-out | `src/agent/decomposition/fan_out.py` | `enqueue_child_jobs()` |
| 13 | **Create** — fan-in | `src/agent/decomposition/fan_in.py` | `execute_merge()` |
| 14 | **Create** — atomicity | `src/agent/decomposition/atomicity.py` | `test_atomicity()`, `AtomicityResult` |
| 15 | **Create** — init | `src/agent/decomposition/__init__.py` | Public exports |
| 16 | **Modify** — add method | `src/agent/supervisor.py` | Add `decompose_task()` method |

### A.13 Key Naming Conventions Summary

| Convention | Example |
|------------|---------|
| Classes | `PascalCase` — `DecompositionOrchestrator`, `JoinHandle` |
| Functions | `snake_case` — `validate_dag()`, `test_atomicity()` |
| Enums | `str, Enum` — `LifecycleState`, `JobState` |
| Dataclasses | `@dataclass(frozen=True)` for value objects |
| Models | `BaseModel` for mutable persisted objects |
| Protocols | `Protocol` with `@runtime_checkable` |
| Stores | `ABC` base + `InMemory*` concrete |
| File headers | `"""Docstring — brief purpose."""` with `from __future__ import annotations` |
| Imports | Absolute: `from src.agent.types.decomposition import DecompositionPlan` |

