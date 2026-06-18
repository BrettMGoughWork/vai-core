"""S5 Composition Root — Adapter-stratum wiring for S4→S5 handoff.

Module-level initialisation runs once at import time, producing a wired
``s5_adapter`` that ``platform/transport/app.py`` imports.

The composition root lives in the **adapter** stratum so it can legally
import from infrastructure (``src.runtime.*``), adapter (``src.agent.*``),
and capability (``src.capabilities.*``).
"""

from __future__ import annotations

from typing import Any, List
from uuid import uuid4

from src.capabilities.contracts import DiscoveredSkill

# ── Infrastructure imports (adapter→infrastructure: allowed) ─────────
from src.runtime.llm.types import CoreLLMResponse, RuntimeConfig

# ── Adapter imports (adapter→adapter: allowed) ────────────────────────
from src.agent.adapters.gateway_adapter import AgentGatewayAdapter
from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
from src.agent.registry import AgentIdentity, AgentMetadata, AgentRegistry
from src.agent.strategy_router import StrategyRouter
from src.agent.supervisor import Supervisor
from src.agent.wiring.composition import wire_planner
from src.agent.workflow import WorkflowRegistry
from src.agent.workflow.loader import load_workflows_from_yaml

# ── Agent registry ────────────────────────────────────────────────────
_registry = AgentRegistry()
_registry.register_agent(AgentMetadata(
    identity=AgentIdentity(
        agent_id="default-agent",
        name="Default Agent",
        description="Default conversational agent",
    ),
    capabilities=["conversational"],
))
_registry.register_agent(AgentMetadata(
    identity=AgentIdentity(
        agent_id="tools-workflow",
        name="Tools Workflow Agent",
        description="Agent that dispatches tool execute jobs via S4B",
    ),
    capabilities=["conversational"],
))
_registry.register_agent(AgentMetadata(
    identity=AgentIdentity(
        agent_id="waiting-agent",
        name="Waiting Agent",
        description="Agent that pauses for user input",
    ),
    capabilities=["conversational"],
))
_registry.register_agent(AgentMetadata(
    identity=AgentIdentity(
        agent_id="multi-step",
        name="Multi-Step Analysis Agent",
        description="Agent with a two-step analysis workflow",
    ),
    capabilities=["conversational"],
))

# ── Workflow registry (loaded from YAML files) ────────────────────────
_wf_registry = WorkflowRegistry()
for defn in load_workflows_from_yaml("config/workflows"):
    _wf_registry.register(defn)

# ── In-memory S4 job queue ───────────────────────────────────────────
_job_call_count: int = 0


def _submit_job(payload: dict[str, Any]) -> str:
    """Record a job submission and return a synthetic job ID."""
    global _job_call_count  # noqa: PLW0603
    _job_call_count += 1
    return f"job-{_job_call_count}-{uuid4().hex[:8]}"


def _execute_tool_inline(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Execute a known tool synchronously, bypassing S4B.

    Returns the result dict if the tool is recognised, or *None* to
    fall through to S4B dispatch.
    """
    skill_name = payload.get("skill_name", "")
    arguments = payload.get("arguments", {})
    if skill_name == "test_tool":
        return {
            "status": "success",
            "message": (
                f"Tool '{skill_name}' executed with "
                f"args: {arguments}"
            ),
            "outputs": arguments,
        }
    return None  # unknown → dispatch to S4B


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
    from src.strategy.planning.s1_contract.s1_client import set_llm_transport

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
        text = _llm_transport.complete(prompt)
        return CoreLLMResponse(text=text, tool_name=None, tool_args=None)


# ── Wired S2 Planner ────────────────────────────────────────────────
_s1_executor = _S1Executor()
_wired_planner = wire_planner(s1_executor=_s1_executor)


# ── Wired StrategyRouter → Supervisor ───────────────────────────────
# Provide a minimal capability discoverer (stub — expand when S3 registry is wired)
def _discover_capabilities() -> list[DiscoveredSkill]:
    return [
        DiscoveredSkill(
            name="test_tool",
            description="Test tool for demonstrating S3 capability execution",
        ),
    ]


def _execute_plan_step(step_payload: dict[str, Any]) -> dict[str, Any]:
    """Execute a single plan step inline.

    Routes the step to the appropriate handler based on ``skill_ref``:
    - ``test_tool`` → inline tool executor
    - ``llm_call``  → S1 LLM transport
    - anything else → unknown skill result
    """
    step_id = step_payload.get("step_id", "")
    skill_ref = step_payload.get("skill_ref", "")
    inputs = step_payload.get("inputs", {})
    description = step_payload.get("description", "")

    if skill_ref == "test_tool":
        result = _execute_tool_inline({
            "skill_name": "test_tool",
            "arguments": inputs,
        })
        return {
            "status": "success",
            "message": result.get("message", f"Tool '{skill_ref}' executed"),
            "step_id": step_id,
            "outputs": result.get("outputs", inputs),
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


_strategy_router = StrategyRouter(
    planner=_wired_planner.plan,
    capability_discoverer=_discover_capabilities,
    submit_s4_job=_submit_job,
    step_executor=_execute_plan_step,
)

# ── Wired Supervisor ────────────────────────────────────────────────
_store = MemoryAgentStateStore()
_supervisor = Supervisor(
    registry=_registry,
    store=_store,
    workflow_registry=_wf_registry,
    submit_job_callable=_submit_job,
    strategy_router=_strategy_router,
    inline_tool_executor=_execute_tool_inline,
)
s5_adapter = AgentGatewayAdapter(_supervisor)
