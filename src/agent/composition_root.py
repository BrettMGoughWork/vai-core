"""S5 Composition Root — Adapter-stratum wiring for S4→S5 handoff.

Module-level initialisation runs once at import time, producing a wired
``s5_adapter`` that ``platform/transport/app.py`` imports.

The composition root lives in the **adapter** stratum so it can legally
import from infrastructure (``src.runtime.*``), adapter (``src.agent.*``),
and capability (``src.capabilities.*``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List

# Load .env into the process environment BEFORE any module-level init that
# depends on env vars (e.g. MCP client config resolution expands ${VAR}
# placeholders via os.path.expandvars).
from dotenv import load_dotenv, find_dotenv

# Walk up the directory tree from this file's location to find the project-root
# .env file, rather than relying on the current working directory (which may
# differ when the server is started from a different directory, e.g. systemd).
_env_path = find_dotenv(usecwd=False, raise_error_if_not_found=False)
if not _env_path:
    # Fallback: resolve .env relative to the project root (this file is in
    # src/agent/; project root is two levels up).
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    _env_path = str(_env_path)
load_dotenv(dotenv_path=_env_path, override=True)

from src.capabilities.patterns.pattern_loader import load_patterns_from_directory
from src.capabilities.patterns.pattern_registry import PatternRegistry
from src.capabilities.primitives.mcp import MCPPrimitive
from src.capabilities.primitives.mcp_client import MCPClientManager
from src.capabilities.primitives.fetch import load_all_primitives as load_fetch_primitives
from src.capabilities.primitives.stdlib import load_all_primitives as load_stdlib_primitives
from src.capabilities.primitives.custom import load_all_primitives as load_custom_primitives
from src.capabilities.registry.primitive_registry import PrimitiveRegistry

# ── Infrastructure imports (adapter→infrastructure: allowed) ─────────
from src.runtime.llm.types import RuntimeConfig

# ── Adapter imports (adapter→adapter: allowed) ────────────────────────
from src.agent.adapters.gateway_adapter import AgentGatewayAdapter
from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
from src.agent.adapters.sessioned_adapter import SessionedAdapter
from src.agent import load_agents_from_directory
from src.agent.registry import AgentRegistry
from src.agent.strategy_router import StrategyRouter
from src.agent.supervisor import Supervisor
from src.agent.workflow import (
    EventBus,
    InMemoryJobQueue,
    TriggerRouter,
    UserInteractionManager,
    WorkflowEngine,
    WorkflowRegistry,
)
from src.agent.workflow.loader import load_workflows_from_yaml
from src.agent.workflow.primitive_tool_adapter import PrimitiveToolAdapter
from src.agent.workflow.workflow_tool_adapter import WorkflowToolAdapter
from src.agent.planner.todo_orchestrator import TodoOrchestrator
from src.agent.council.loader import load_councils_from_directory
from src.agent.council.orchestrator import CouncilOrchestrator
from src.agent.council.registry import CouncilRegistry
from src.platform.runtime.control_plane import ControlPlane
from src.platform.runtime.job_store.job_store import InMemoryJobStore
from src.agent.decomposition.llm_decomposer import LLMDecomposer
from src.agent.decomposition.orchestrator import DecompositionOrchestrator
from src.platform.queue.queue import InMemoryQueue
from src.platform.runtime.job_store.backends.in_memory_join_store import InMemoryJoinStore
from src.agent.decomposition.subtask_worker import SubtaskWorker
from src.agent.decomposition.continuation_worker import ContinuationWorker
from src.agent.decomposition.merge import execute_merge as _execute_merge
from src.agent.decomposition.worker_pool import DecompositionWorkerPool
from src.platform.runtime.worker import Worker
from src.platform.runtime.job import Job
from src.platform.runtime.job_state import JobState, transition
from src.gateway.normalization import ChannelMessage
import uuid as _uuid

# ── Agent registry (loaded from declarative YAML) ─────────────────────
_registry = AgentRegistry()
load_agents_from_directory(_registry, "config/agents")
load_agents_from_directory(_registry, "config/agents/council")

# Validate deferral graph for acyclicity before any runtime operations
# (catches cycles, self-references, and references to unknown agents)
from src.agent.deferral import validate_deferral_graph  # noqa: E402
_deferral_errors = validate_deferral_graph(_registry)
if _deferral_errors:
    _error_msgs = "\n  ".join(str(e) for e in _deferral_errors)
    raise ValueError(f"Deferral graph validation failed:\n  {_error_msgs}")

# ── Workflow registry (loaded from YAML files) ────────────────────────
wf_registry = WorkflowRegistry()
for defn in load_workflows_from_yaml("config/workflows"):
    wf_registry.register(defn)

# ── Council definitions + registry (loaded from YAML files) ──────────
_council_defs = load_councils_from_directory("config/councils")
_council_registry = CouncilRegistry()
for _cd in _council_defs:
    _council_registry.register(_cd)

# ── Primitive registry (loaded from stdlib + custom) ────────────────
_primitive_registry = PrimitiveRegistry()
_primitives_loaded = load_stdlib_primitives(_primitive_registry)
_custom_primitives_loaded = load_custom_primitives(_primitive_registry)
_fetch_primitives_loaded = load_fetch_primitives(_primitive_registry)

# ── Pattern registry (loaded from declarative YAML files) ──────────
_pattern_registry = PatternRegistry()
_patterns_loaded = load_patterns_from_directory(_pattern_registry, "config/patterns")

# ── MCP client manager (manages MCP server subprocesses) ─────────────
_mcp_client_manager = MCPClientManager("config/mcp_servers.yaml")

# ── Auto-discover MCP tools and register as primitives ──────────────
# Phase 8.5: MCP tools are auto-discovered via `tools/list` protocol,
# bypassing the legacy YAML plugin ceremony. Each tool becomes an
# MCPPrimitive registered as "mcp.<server>.<tool>" in the registry.
_mcp_discovered = _mcp_client_manager.discover_tools()
_mcp_primitive_count = 0
for _server_name, _tools in _mcp_discovered.items():
    for _tool_def in _tools:
        _primitive_name = f"mcp.{_server_name}.{_tool_def['name']}"
        try:
            _primitive = MCPPrimitive(
                name=_primitive_name,
                description=_tool_def.get("description", ""),
                server_name=_server_name,
                tool_name=_tool_def["name"],
                input_schema=_tool_def.get("input_schema", {"type": "object", "properties": {}}),
            )
            _primitive_registry.register(_primitive_name, _primitive)
            _mcp_primitive_count += 1
        except ValueError:
            pass  # already registered (e.g. via plugin manifest) — skip
if _mcp_primitive_count > 0:
    import logging
    logging.getLogger(__name__).info(
        "Auto-discovered %d MCP tools from %d server(s)",
        _mcp_primitive_count, len(_mcp_discovered),
    )

# ── Plugin loader ───────────────────────────────────────────────────
# Skills layer has been removed (Phase 4 clean sweep). Plugins that
# previously defined skills should now register Primitives directly.
# The PluginLoader is retained for backward-compatible plugin YAML loading
# but will be migrated to a pure primitive-based model in a future sprint.

# ── Search config (injected into primitive context for stdlib.search) ────
_search_config = None
try:
    import yaml as _yaml
    _config_path = Path("config/config.yaml")
    if _config_path.exists():
        with open(_config_path, "r") as _f:
            _raw_config = _yaml.safe_load(_f) or {}
        _search_raw = _raw_config.get("search")
        if _search_raw:
            from src.domain.types.config import SearchConfig
            _search_config = SearchConfig.from_yaml(_search_raw)
except Exception:
    pass  # Search is optional — primitives handle missing config gracefully

# ── Shared context injected into every primitive.execute() call ──────
_PRIMITIVE_CONTEXT: dict[str, object] = {
    "mcpclient": _mcp_client_manager,
    "workspace_path": os.getcwd(),
    "search_config": _search_config,
}


def _execute_tool_inline(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Execute a known tool synchronously, bypassing S4B.

    Looks up the skill name in the real ``PrimitiveRegistry``.  Returns
    the result dict if the primitive is recognised, or *None* to fall
    through to S4B dispatch.
    """
    skill_name = payload.get("skill_name", "")
    arguments = payload.get("arguments", {})

    primitive = _primitive_registry.get(skill_name)
    if primitive is None:
        return None  # unknown → dispatch to S4B

    try:
        result = primitive.execute(arguments, context=_PRIMITIVE_CONTEXT)
        return {
            "status": result.status,
            "message": (
                f"Primitive '{skill_name}' executed successfully"
                if result.status == "success"
                else f"Primitive '{skill_name}' failed: {result.error}"
            ),
            "outputs": result.data if result.data is not None else {},
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Primitive '{skill_name}' raised: {exc}",
            "outputs": {},
        }




# ── S1 → S2: inject LLM transport via DI slot ──────────────────────
def _build_llm_transport():
    """Build the LLM transport from config.  Returns None on failure."""
    try:
        import yaml
        from pathlib import Path

        from src.runtime.llm.builder import create_llm_transport

        config_path = Path("config/config.yaml")
        if not config_path.exists():
            return None

        with open(config_path, "r") as f:
            raw = yaml.safe_load(f)

        llm_raw = raw.get("llm", {})
        provider_name = llm_raw.get("provider", "")
        if not provider_name:
            return None

        model = llm_raw.get("model", "default")
        variants = llm_raw.get("model_variants", {})
        active = llm_raw.get("active_variant", "")
        if variants and active in variants:
            model = variants[active]

        llm_config = RuntimeConfig(
            provider=provider_name,
            model=model,
            temperature=llm_raw.get("temperature", 0.0),
            max_tokens=llm_raw.get("max_tokens", 4096),
        )
        return create_llm_transport(llm_config)
    except Exception:
        return None


_llm_transport = _build_llm_transport()
if _llm_transport is not None:
    from src.runtime.llm.client import set_llm_transport

    set_llm_transport(_llm_transport)


# ── S1 Executor (S5 → S1 protocol adapter) ──────────────────────────


# ── Shared MemoryGovernance ──────────────────────────────────────────
# Created once at the composition root so StrategyRouter and any other
# component share the same memory stores.
from src.agent.memory.segment_memory import SegmentMemory
from src.agent.memory.subgoal_memory import SubgoalMemory
from src.agent.memory.plan_memory import PlanMemory
from src.agent.memory.drift_memory import DriftMemory
from src.agent.memory.governance.memory_governance import MemoryGovernance
from src.agent.memory.compaction import CompactionConfig, CompactionOrchestrator

_segment_memory = SegmentMemory()
_subgoal_memory = SubgoalMemory()
_plan_memory = PlanMemory()
_drift_memory = DriftMemory()

# ── EvictionOrchestrator ──────────────────────────────────────────────
from src.agent.memory.eviction.eviction_orchestrator import EvictionOrchestrator

_eviction_orchestrator = EvictionOrchestrator(
    segment_memory=_segment_memory,
    subgoal_memory=_subgoal_memory,
    plan_memory=_plan_memory,
    drift_memory=_drift_memory,
)


def _wire_eviction_orchestrator() -> None:
    """Late-bind eviction orchestrator into client.py and MemoryGovernance.

    Called after MemoryGovernance is constructed so we can inject the
    eviction orchestrator into both.
    """
    from src.runtime.llm.client import set_eviction_orchestrator
    set_eviction_orchestrator(_eviction_orchestrator)


# ── CompactionOrchestrator ─────────────────────────────────────────────
_compaction_config = CompactionConfig()
try:
    import yaml as _comp_yaml
    _comp_path = Path("config/config.yaml")
    if _comp_path.exists():
        with open(_comp_path, "r") as _f:
            _comp_raw = _comp_yaml.safe_load(_f) or {}
        _compaction_cfg_raw = _comp_raw.get("compaction", {})
        if _compaction_cfg_raw:
            _compaction_config = CompactionConfig.from_dict(_compaction_cfg_raw)
except Exception:
    pass  # compaction config is optional — defaults are safe

_llm_complete = getattr(_llm_transport, "complete", None) if _llm_transport else None
_compaction_orchestrator = CompactionOrchestrator(
    llm_complete=_llm_complete,
    config=_compaction_config,
    subgoal_memory=_subgoal_memory,
) if _llm_complete else None

if _compaction_orchestrator is not None:
    from src.runtime.llm.client import set_compaction_orchestrator
    set_compaction_orchestrator(_compaction_orchestrator)

_shared_governance = MemoryGovernance(
    subgoal_memory=_subgoal_memory,
    segment_memory=_segment_memory,
    plan_memory=_plan_memory,
    drift_memory=_drift_memory,
    eviction_orchestrator=_eviction_orchestrator,
    compaction_orchestrator=_compaction_orchestrator,
)

# Late-bind eviction orchestrator into client.py (avoids circular imports)
_wire_eviction_orchestrator()


# ── Wired StrategyRouter → Supervisor ───────────────────────────────
state_store = MemoryAgentStateStore()
_job_queue = InMemoryJobQueue()

_strategy_router = StrategyRouter(
    submit_s4_job=_job_queue.submit,
    governance=_shared_governance,
)

# ── Concrete S2PlanDecomposer (LLM-based task decomposition) ────────
_decomposer = LLMDecomposer(strategy_router=_strategy_router)

# ── Wired Supervisor ────────────────────────────────────────────────
_workflow_engine = WorkflowEngine(
    wf_registry,
    pattern_registry=_pattern_registry,
    council_registry=_council_registry,
)
_interaction_manager = UserInteractionManager(_workflow_engine)
_workflow_tool_adapter = WorkflowToolAdapter(wf_registry)
_primitive_tool_adapter = PrimitiveToolAdapter(_primitive_registry)

# ── ControlPlane + TodoOrchestrator (Sprint 12b — first-class capability) ──
_control_plane = ControlPlane(job_store=InMemoryJobStore())
_todo_orchestrator_queue = InMemoryQueue()
_todo_orchestrator = TodoOrchestrator(
    workflow_engine=_workflow_engine,
    strategy_router=_strategy_router,
    inline_tool_executor=_execute_tool_inline,
    queue=_todo_orchestrator_queue,
    control_plane=_control_plane,
    timeout_seconds=300,
    max_iterations_per_goal=10,
)

# ── Decomposition Orchestrator (agent task fan-out/fan-in) ────────────
def _make_decomp_enqueue_fn(
    queue: InMemoryQueue,
    control_plane: ControlPlane,
) -> Any:
    """Build the enqueue callback for ``DecompositionOrchestrator``.

    The returned callable accepts a ``job_dict`` from the orchestrator's
    ``_enqueue_subtasks`` / ``_enqueue_continuation`` helpers, converts
    it to a proper ``Job``, registers it with the control plane, and
    pushes it onto the S4 queue.
    """
    def _enqueue(job_dict: dict) -> str:
        payload = ChannelMessage(
            input={
                "subtask_description": job_dict.get("subtask_description", ""),
                "target_agent_id": job_dict.get("target_agent_id"),
                "target_skill_id": job_dict.get("target_skill_id"),
                "arguments": job_dict.get("arguments", {}),
            },
            metadata={
                "source": "decomposition",
                "job_type": job_dict.get("job_type", "default"),
                "plan_id": job_dict.get("plan_id"),
                "join_handle_id": job_dict.get("join_handle_id"),
                "merge_strategy": job_dict.get("merge_strategy"),
                "merge_agent_id": job_dict.get("merge_agent_id"),
                "merge_prompt_template": job_dict.get("merge_prompt_template"),
                "subtask_description": job_dict.get("subtask_description", ""),
            },
            channel="planner",
        )
        job = Job(
            job_id=job_dict.get("job_id", str(_uuid.uuid4())),
            job_type=job_dict.get("job_type", "default"),
            parent_job_id=job_dict.get("parent_job_id"),
            priority=job_dict.get("priority", 0),
            max_retries=job_dict.get("max_retries", 0),
            timeout_seconds=job_dict.get("timeout_seconds", 300),
            plan_id=job_dict.get("plan_id"),
            subtask_id=job_dict.get("subtask_id"),
            depends_on=job_dict.get("depends_on", []),
            payload=payload,
        )
        control_plane.register_job(job)

        # BLOCKED dispatch filter: jobs with unsatisfied depends_on stay
        # BLOCKED in the store until handle_child_success transitions them.
        if job.depends_on:
            job.state = transition(job.state, JobState.BLOCKED)
            control_plane.save_checkpoint(job)
            # Do NOT push to queue — handle_child_success will push when
            # all dependencies are satisfied.
        else:
            queue.push(job)

        return job.job_id
    return _enqueue

_decomposition_queue = InMemoryQueue()
_join_store = InMemoryJoinStore()
_decomp_enqueue = _make_decomp_enqueue_fn(_decomposition_queue, _control_plane)
_decomposition_orchestrator = DecompositionOrchestrator(
    join_store=_join_store,
    enqueue_fn=_decomp_enqueue,
    enqueue_continuation_fn=_decomp_enqueue,
)

_supervisor = Supervisor(
    registry=_registry,
    store=state_store,
    workflow_registry=wf_registry,
    workflow_engine=_workflow_engine,
    submit_job_callable=_job_queue.submit,
    strategy_router=_strategy_router,
    inline_tool_executor=_execute_tool_inline,
    interaction_manager=_interaction_manager,
    workflow_tool_adapter=_workflow_tool_adapter,
    primitive_tool_adapter=_primitive_tool_adapter,
    pattern_registry=_pattern_registry,
    todo_orchestrator=_todo_orchestrator,
    council_registry=_council_registry,
    job_store=_control_plane.job_store,
    decomposition_orchestrator=_decomposition_orchestrator,
    decomposer=_decomposer,
)

# ── Event Bus & Trigger Router (Sprint 6 — transport layer) ────────
_event_bus = EventBus()
_trigger_router = TriggerRouter(wf_registry, _workflow_engine)
_trigger_router.subscribe_all(_event_bus)

# ── Council Orchestrator (Sprint C1 — multi-agent arbitration) ─────────
_council_orchestrator = CouncilOrchestrator(supervisor=_supervisor)

# Late-bind council_orchestrator into Supervisor (circular dependency:
# Supervisor needs CouncilOrchestrator, CouncilOrchestrator needs Supervisor)
_supervisor._council_orchestrator = _council_orchestrator
_supervisor._workflow_invoker._council_orchestrator = _council_orchestrator

# ── Decomposition Workers (agent task fan-out/fan-in processing) ──────
def _run_temp_agent(agent_id: str, prompt: str) -> dict:
    """Create, activate, run to completion, and extract response."""
    from src.agent.contracts import AgentMessage
    from src.agent.interfaces.agent_state import LifecycleState
    from src.platform.observability import logging as _obs_logger

    # Log the agent invocation (visible in --verbose mode)
    _obs_logger.log(
        "info",
        "SubtaskWorker invoking agent",
        {"agent_id": agent_id, "prompt_length": len(prompt)},
        component="decomposition",
        _correlation_id="",
        _trace_id="",
    )

    try:
        state = _supervisor.create_agent(agent_id)
    except Exception as exc:
        msg = f"create_agent({agent_id!r}) failed: {type(exc).__name__}: {exc}"
        import sys as _sys
        print(f"[decomp] {msg}", file=_sys.stderr, flush=True)
        raise

    try:
        state = _supervisor.activate_agent(state, AgentMessage(message=prompt))
    except Exception as exc:
        msg = f"activate_agent({agent_id!r}) failed: {type(exc).__name__}: {exc}"
        import sys as _sys
        print(f"[decomp] {msg}", file=_sys.stderr, flush=True)
        raise

    _MAX_TEMP_STEPS = 100
    for step_idx in range(_MAX_TEMP_STEPS):
        try:
            state = _supervisor.run_agent_step(state)
        except Exception as exc:
            import sys as _sys, traceback as _tb
            print(f"[decomp] run_agent_step({agent_id!r}) step {step_idx} failed:",
                  file=_sys.stderr, flush=True)
            _tb.print_exc(file=_sys.stderr)
            raise
        if state.lifecycle_state.is_terminal():
            break
        # Agents that enter WAITING cannot resolve autonomously in a
        # temp context — treat as terminal (error).
        # AWAITING_CHILDREN is NOT included here because decompose_task
        # is synchronous (blocks within a single run_agent_step call)
        # and always resumes to RUNNING before returning, so it is
        # never visible at the loop level.
        if state.lifecycle_state == LifecycleState.WAITING:
            break

    response = _supervisor.get_response(state)
    return {
        "output": (
            response.reply
            if (response and response.reply)
            else str(state.lifecycle_state.value)
        ),
        "status": (
            "success"
            if state.lifecycle_state == LifecycleState.COMPLETED
            else "error"
        ),
        "done": True,
    }

_subtask_worker = SubtaskWorker(
    run_temp_agent=_run_temp_agent,
    inline_tool_executor=_execute_tool_inline,
)
_continuation_worker = ContinuationWorker(
    join_store=_join_store,
    job_store=_control_plane.job_store,
    execute_merge=_execute_merge,
)


def _decomposition_executor(
    payload: Any,
    execution_context: Any = None,
    resume_token: Any = None,
    **kwargs: Any,
) -> dict:
    """Route decomposition jobs to the appropriate worker by job_type."""
    metadata = (
        payload.metadata
        if isinstance(payload, ChannelMessage)
        else {}
    )
    job_type = metadata.get("job_type", "subtask")
    if job_type == "continuation":
        return _continuation_worker(
            payload, execution_context, resume_token, **kwargs,
        )
    return _subtask_worker(
        payload, execution_context, resume_token, **kwargs,
    )


def _on_decomp_job_complete(job: Job) -> None:
    """Post-execution hook: unblock siblings and update JoinHandle."""
    from src.platform.runtime.diagnostics import diag
    diag(f"_on_decomp_job_complete(job_id={job.job_id}, state={job.state})")

    from src.platform.runtime.scheduling.dependency import (
        handle_child_failure,
        handle_child_success,
    )
    if job.state == JobState.SUCCEEDED:
        diag(f"  -> handle_child_success({job.job_id})")
        handle_child_success(
            job.job_id,
            job_store=_control_plane.job_store,
            join_store=_join_store,
            queue=_decomposition_queue,
        )
        diag(f"  <- handle_child_success({job.job_id}) done")
    elif job.state in (JobState.FAILED, JobState.POISON):
        diag(f"  -> handle_child_failure({job.job_id})")
        handle_child_failure(
            job.job_id,
            job_store=_control_plane.job_store,
            join_store=_join_store,
            queue=_decomposition_queue,
        )
        diag(f"  <- handle_child_failure({job.job_id}) done")
    else:
        diag(f"  ** UNHANDLED state {job.state} for job {job.job_id}")


def _decomp_worker_factory() -> Worker:
    """Create a single Worker bound to the shared decomposition resources."""
    return Worker(
        executor=_decomposition_executor,
        queue=_decomposition_queue,
        control_plane=_control_plane,
        timeout_seconds=300,
        on_job_complete=_on_decomp_job_complete,
    )

# ── Pool size from config.yaml (fallback: env var / default 2) ──────
_pool_size_raw: str | None = None
try:
    import yaml as _pool_yaml
    _pool_cfg_path = Path("config/config.yaml")
    if _pool_cfg_path.exists():
        with open(_pool_cfg_path, "r") as _f:
            _raw = _pool_yaml.safe_load(_f) or {}
        _pool_size_raw = (
            _raw.get("decomposition", {}).get("worker_pool", {}).get("pool_size")
        )
except Exception:
    pass  # fallback to default

if _pool_size_raw is not None:
    _pool_size = max(1, int(_pool_size_raw))
    # silence unused-import lint when the fallback path is taken
    del _pool_size_raw
else:
    _pool_size = None

_decomposition_worker_pool = DecompositionWorkerPool(
    worker_factory=_decomp_worker_factory,
    pool_size=_pool_size,
)

# Late-bind decomposition worker pool into Supervisor so decompose_task()
# and parallelize() can start pool threads and poll for completion.
_supervisor._decomposition_worker_pool = _decomposition_worker_pool

import atexit as _atexit
_atexit.register(_decomposition_worker_pool.stop)

s5_adapter: GatewayAgentAdapter = SessionedAdapter(
    AgentGatewayAdapter(_supervisor),
)
s5_event_bus: EventBus = _event_bus

# Exported for CLI introspection (e.g., /agent command, /agents list, /workflows list, /patterns list)
agent_registry: AgentRegistry = _registry
workflow_registry: WorkflowRegistry = wf_registry
pattern_registry: PatternRegistry = _pattern_registry
council_defs: list = _council_defs
council_registry: CouncilRegistry = _council_registry
council_orchestrator: CouncilOrchestrator = _council_orchestrator
