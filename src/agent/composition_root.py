"""S5 Composition Root — Adapter-stratum wiring for S4→S5 handoff.

Module-level initialisation runs once at import time, producing a wired
``s5_adapter`` that ``platform/transport/app.py`` imports.

The composition root lives in the **adapter** stratum so it can legally
import from infrastructure (``src.runtime.*``), adapter (``src.agent.*``),
and capability (``src.capabilities.*``).
"""

from __future__ import annotations

import os
from typing import Any, List

# Load .env into the process environment BEFORE any module-level init that
# depends on env vars (e.g. MCP client config resolution expands ${VAR}
# placeholders via os.path.expandvars).
from dotenv import load_dotenv

load_dotenv(override=True)

from src.capabilities.patterns.pattern_loader import load_patterns_from_directory
from src.capabilities.patterns.pattern_registry import PatternRegistry
from src.capabilities.primitives.mcp import MCPPrimitive
from src.capabilities.primitives.mcp_client import MCPClientManager
from src.capabilities.primitives.fetch import load_all_primitives as load_fetch_primitives
from src.capabilities.primitives.stdlib import load_all_primitives as load_stdlib_primitives
from src.capabilities.primitives.custom import load_all_primitives as load_custom_primitives
from src.capabilities.registry.primitive_registry import PrimitiveRegistry

# ── Infrastructure imports (adapter→infrastructure: allowed) ─────────
from src.runtime.llm.types import CoreLLMResponse, RuntimeConfig

# ── Adapter imports (adapter→adapter: allowed) ────────────────────────
from src.agent.adapters.gateway_adapter import AgentGatewayAdapter
from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
from src.agent.adapters.sessioned_adapter import SessionedAdapter
from src.agent import load_agents_from_directory
from src.agent.registry import AgentRegistry
from src.agent.strategy_router import StrategyRouter
from src.agent.supervisor import Supervisor
from src.agent.wiring.composition import wire_planner
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

# ── Agent registry (loaded from declarative YAML) ─────────────────────
_registry = AgentRegistry()
load_agents_from_directory(_registry, "config/agents")

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

# ── Shared context injected into every primitive.execute() call ──────
_PRIMITIVE_CONTEXT: dict[str, object] = {
    "mcpclient": _mcp_client_manager,
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


class _S1Executor:
    """Minimal S1Executor wrapping the LLM transport."""

    def complete(
        self,
        prompt: str,
        context: dict[str, object] | None = None,
    ) -> CoreLLMResponse:
        if _llm_transport is None:
            return CoreLLMResponse(text="", tool_name=None, tool_args=None)
        text = _llm_transport.complete(prompt)
        return CoreLLMResponse(text=text, tool_name=None, tool_args=None)

    def complete_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, object]],
        context: dict[str, object] | None = None,
    ) -> CoreLLMResponse:
        if _llm_transport is None:
            return CoreLLMResponse(text="", tool_name=None, tool_args=None)
        messages = [{"role": "user", "content": prompt}]
        if hasattr(_llm_transport, "complete_with_tools"):
            return _llm_transport.complete_with_tools(messages, tools)
        # Fallback: text-only complete if tool-calling not available
        text = _llm_transport.complete(prompt)
        return CoreLLMResponse(text=text, tool_name=None, tool_args=None)


# ── Wired S2 Planner ────────────────────────────────────────────────
_s1_executor = _S1Executor()
_wired_planner = wire_planner(s1_executor=_s1_executor)


# ── Shared MemoryGovernance ──────────────────────────────────────────
# Created once at the composition root so StrategyRouter, planner, and
# any other component share the same memory stores and governance layer.
from src.strategy.memory.segment_memory import SegmentMemory
from src.strategy.memory.subgoal_memory import SubgoalMemory
from src.strategy.memory.plan_memory import PlanMemory
from src.strategy.memory.drift_memory import DriftMemory
from src.strategy.memory.governance.memory_governance import MemoryGovernance

_segment_memory = SegmentMemory()
_subgoal_memory = SubgoalMemory()
_plan_memory = PlanMemory()
_drift_memory = DriftMemory()
_shared_governance = MemoryGovernance(
    subgoal_memory=_subgoal_memory,
    segment_memory=_segment_memory,
    plan_memory=_plan_memory,
    drift_memory=_drift_memory,
)


# ── Wired StrategyRouter → Supervisor ───────────────────────────────
def _discover_capabilities() -> list[dict]:
    """Return all primitives and patterns from the real registries as capability definitions."""
    capabilities: list[dict] = []
    for p in _primitive_registry.list():
        capabilities.append({"name": p.name, "description": p.description, "type": "tool"})
    for p in _pattern_registry.list():
        capabilities.append({"name": p.pattern_id, "description": p.description, "type": "pattern"})
    return capabilities


def _execute_plan_step(step_payload: dict[str, Any]) -> dict[str, Any]:
    """Execute a single plan step inline.

    Routes the step to the appropriate handler based on ``skill_ref``:
    - registered stdlib primitive → ``PrimitiveRegistry``
    - ``llm_call`` / ``llm``     → S1 LLM transport
    - anything else               → unknown skill result
    """
    step_id = step_payload.get("step_id", "")
    skill_ref = step_payload.get("skill_ref", "")
    inputs = step_payload.get("inputs", {})
    description = step_payload.get("description", "")

    # Look up real primitives from the registry
    primitive = _primitive_registry.get(skill_ref)
    if primitive is not None:
        try:
            result = primitive.execute(inputs, context=_PRIMITIVE_CONTEXT)
            return {
                "status": result.status,
                "message": (
                    f"Primitive '{skill_ref}' executed successfully"
                    if result.status == "success"
                    else f"Primitive '{skill_ref}' failed: {result.error}"
                ),
                "step_id": step_id,
                "outputs": result.data if result.data is not None else {},
            }
        except Exception as exc:
            return {
                "status": "error",
                "message": f"Primitive '{skill_ref}' raised: {exc}",
                "step_id": step_id,
                "outputs": {},
            }

    if skill_ref in ("llm_call", "llm"):
        prompt = description or inputs.get("prompt", f"Execute step: {step_id}")
        response = _s1_executor.complete(prompt)
        return {
            "status": "success",
            "message": response.text or f"LLM responded to step '{step_id}'",
            "step_id": step_id,
            "outputs": {"response": response.text},
        }

    return {
        "status": "unknown",
        "message": f"No handler for skill_ref='{skill_ref}' (step '{step_id}')",
        "step_id": step_id,
        "outputs": {},
    }


state_store = MemoryAgentStateStore()
_job_queue = InMemoryJobQueue()

_strategy_router = StrategyRouter(
    planner=_wired_planner.plan,
    capability_discoverer=_discover_capabilities,
    submit_s4_job=_job_queue.submit,
    step_executor=_execute_plan_step,
    governance=_shared_governance,
)

# ── Wired Supervisor ────────────────────────────────────────────────
_workflow_engine = WorkflowEngine(wf_registry, pattern_registry=_pattern_registry)
_interaction_manager = UserInteractionManager(_workflow_engine)
_workflow_tool_adapter = WorkflowToolAdapter(wf_registry)
_primitive_tool_adapter = PrimitiveToolAdapter(_primitive_registry)
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
)

# ── Event Bus & Trigger Router (Sprint 6 — transport layer) ────────
_event_bus = EventBus()
_trigger_router = TriggerRouter(wf_registry, _workflow_engine)
_trigger_router.subscribe_all(_event_bus)

s5_adapter: GatewayAgentAdapter = SessionedAdapter(
    AgentGatewayAdapter(_supervisor),
)
s5_event_bus: EventBus = _event_bus

# Exported for CLI introspection (e.g., /agent command, /agents list, /workflows list, /patterns list)
agent_registry: AgentRegistry = _registry
workflow_registry: WorkflowRegistry = wf_registry
pattern_registry: PatternRegistry = _pattern_registry
