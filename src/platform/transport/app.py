"""FastAPI Gateway — Stratum-4 transport boundary with adapter pattern.

Single ``POST /run`` endpoint that accepts arbitrary JSON, submits it as a job
via the :class:`~src.platform.transport.adapter.PlatformGatewayAdapter`, and
returns the ``job_id``.

The Gateway **never** imports Platform internals directly — it goes through the
adapter interface.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from src.gateway.adapters.platform_adapter import JobRequest
from src.platform.transport.adapter import PlatformGatewayAdapter

# Module-level adapter so gateway and worker share one queue instance
_adapter = PlatformGatewayAdapter()

app = FastAPI(title="Stratum-4 Gateway", version="0.1.0")


@app.post("/run")
def run(payload: dict[str, Any]) -> dict[str, str]:
    """Accept a job request and return a ``job_id``.

    The payload must be a JSON object (dict).  It is converted into a
    :class:`JobRequest`, submitted through the
    :class:`~src.platform.transport.adapter.PlatformGatewayAdapter`, which
    wraps it in a ``ChannelMessage``, creates a ``Job``, registers it via
    the ``ControlPlane``, and pushes it onto the in-memory queue.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    result = _adapter.submit_job(
        JobRequest(
            channel_type="cli",
            message_text=str(payload.get("input", payload)),
            user_id=payload.get("sender"),
            metadata=payload.get("metadata", {}),
        )
    )

    return {"job_id": result.job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    """Retrieve a job's state and result by its ``job_id``.

    Returns ``404`` with a JSON error body if the job is not found.
    """
    status = _adapter.get_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="job not found")

    return {
        "job_id": status.job_id,
        "state": status.state,
        "result": status.output,
    }
