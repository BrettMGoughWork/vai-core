"""FastAPI Gateway — Stratum-4 transport boundary with S5 handoff.

The Gateway imports a pre-wired ``s5_adapter`` from the S5 composition root
(``src.agent.composition_root``).  All adapter-wiring lives there so the
infrastructure stratum stays free of adapter imports.

The Gateway **never** imports S5 internals directly — it goes through the
adapter interface.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from src.agent.composition_root import s5_adapter

# Module-level adapter so gateway stays lightweight
app = FastAPI(title="Stratum-4 Gateway", version="0.1.0")


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
