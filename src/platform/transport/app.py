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

from src.agent.composition_root import (
    s5_adapter,
    state_store,
    wf_registry,
)
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.web import register_web_channel
from src.gateway.channels.web_simple import mount_ui

# Module-level adapter so gateway stays lightweight
app = FastAPI(title="Stratum-4 Gateway", version="0.1.0")

# Module-level channel registry (created once, not per-request)
_channel_registry = ChannelRegistry()
register_web_channel(_channel_registry)

# Mount the Web Channel UI (PWA) — serves index.html at "/" and static assets at "/static"
mount_ui(app)


@app.post("/run")
def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept a JSON payload, normalise it, and hand off to S5.

    The payload is normalised through the channel pipeline, wrapped as an
    ``AgentRequest``, and processed by the S5 Supervisor.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    from src.gateway.entrypoint import submit_channel_input

    result = submit_channel_input(
        _channel_registry, "web", payload, adapter=s5_adapter,
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
    state = state_store.load(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="not found")

    return {
        "job_id": job_id,
        "state": state.lifecycle_state.value,
    }


@app.post("/workflows/{workflow_id}/execute")
def execute_workflow(workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Start a workflow by ID with an optional initial payload.

    Returns the workflow instance ID that can be used to poll progress.
    """
    from src.gateway.entrypoint import submit_channel_input

    payload.setdefault("_workflow_id", workflow_id)
    result = submit_channel_input(
        _channel_registry, "web", payload, adapter=s5_adapter,
    )
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/workflows")
def list_workflows() -> list[dict[str, object]]:
    """List all registered workflow definitions."""
    return [
        {
            "workflow_id": defn.workflow_id,
            "name": defn.name,
            "description": defn.description,
            "steps": list(defn.steps.keys()),
        }
        for defn in wf_registry.list()
    ]
