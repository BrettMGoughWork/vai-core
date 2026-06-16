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


# ── Wired Supervisor ──────────────────────────────────────────────────
_store = MemoryAgentStateStore()
_supervisor = Supervisor(
    registry=_registry,
    store=_store,
    workflow_registry=_wf_registry,
    submit_job_callable=_submit_job,
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
