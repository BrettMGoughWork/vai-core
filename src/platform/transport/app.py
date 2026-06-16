"""FastAPI Gateway — Stratum-4 transport boundary with S5 handoff.

Single ``POST /run`` endpoint that accepts arbitrary JSON, normalises it
through the channel pipeline, and hands off to S5 via the
:class:`~src.gateway.adapters.agent_adapter.GatewayAgentAdapter`.

The Gateway **never** imports S5 internals directly — it goes through the
adapter interface.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from src.gateway.entrypoint import process_channel_input

# Module-level adapter so gateway stays lightweight
app = FastAPI(title="Stratum-4 Gateway", version="0.1.0")

# ---------------------------------------------------------------------------
# In-memory supervisor wiring with all dependencies
# ---------------------------------------------------------------------------
from src.agent.adapters.gateway_adapter import AgentGatewayAdapter
from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
from src.agent.registry import AgentIdentity, AgentMetadata, AgentRegistry
from src.agent.supervisor import Supervisor
from src.agent.workflow import (
    WorkflowDefinition,
    WorkflowRegistry,
    WorkflowStep,
)

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

# ── Workflow registry with a default greeting workflow ────────────────
_wf_registry = WorkflowRegistry()
_wf_registry.register(WorkflowDefinition(
    workflow_id="default-agent",
    name="Conversational Workflow",
    description="Greets the user via conversation",
    version="1.0.0",
    trigger_on=["workflow_request"],
    steps={
        "greet": WorkflowStep(
            step_id="greet",
            step_type="llm_call",
            label="Greet the user",
            config={"prompt": "Respond to the user's message: {{input}}"},
            transitions={"on_success": "__end__"},
        ),
    },
    start_step="greet",
))

# ── In-memory S4 job queue ───────────────────────────────────────────
_job_call_count: int = 0


def _submit_job(payload: dict[str, Any]) -> str:
    """Record a job submission and return a synthetic job ID."""
    global _job_call_count  # noqa: PLW0603
    _job_call_count += 1
    return f"job-{_job_call_count}-{uuid4().hex[:8]}"


# ── S1 → S2: inject LLM transport via DI slot ──────────────────────
# The composition root imports S1 directly — this is the ONLY place.
# S2 never imports S1 types.
from src.runtime.llm.types import RuntimeConfig


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
# Wraps the LLM transport into an S1Executor for the composition root.


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
from src.agent.wiring.composition import wire_planner
from src.runtime.llm.types import CoreLLMResponse

_s1_executor = _S1Executor()
_wired_planner = wire_planner(s1_executor=_s1_executor)


# ── Wired StrategyRouter → Supervisor ───────────────────────────────
from src.agent.strategy_router import StrategyRouter

_strategy_router = StrategyRouter(
    planner=_wired_planner.plan,
    capability_discoverer=None,
    submit_s4_job=_submit_job,
)

# ── Wired Supervisor ────────────────────────────────────────────────
_store = MemoryAgentStateStore()
_supervisor = Supervisor(
    registry=_registry,
    store=_store,
    workflow_registry=_wf_registry,
    submit_job_callable=_submit_job,
    strategy_router=_strategy_router,
)
_s5_adapter = AgentGatewayAdapter(_supervisor)


@app.post("/run")
def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept a JSON payload, normalise it, and hand off to S5.

    The payload is normalised through the channel pipeline, wrapped as an
    ``AgentRequest``, and processed by the S5 Supervisor.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    from src.gateway.channels.registry import ChannelRegistry
    from src.gateway.channels.web import register_web_channel

    reg = ChannelRegistry()
    register_web_channel(reg)

    from src.gateway.entrypoint import submit_channel_input

    result = submit_channel_input(
        reg, "web", payload, adapter=_s5_adapter,
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return result


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    """Retrieve a job's state and result by its ``job_id``. (legacy)

    Returns ``404`` with a JSON error body if the job is not found.
    This endpoint exists for backward compatibility and returns
    agent state info for the given id.
    """
    from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore

    store = MemoryAgentStateStore()
    state = store.load(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="not found")

    return {
        "job_id": job_id,
        "state": state.lifecycle_state.value,
    }
