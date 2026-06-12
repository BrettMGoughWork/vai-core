"""FastAPI Gateway — Stratum-4 transport boundary.

Single ``POST /run`` endpoint that accepts arbitrary JSON, normalizes it into
a ``ChannelMessage`` v1 via ``gateway_to_channel_message``, creates a ``Job``,
pushes it onto the in-memory queue, and returns the ``job_id``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from src.platform.queue.queue import InMemoryQueue
from src.platform.transport.normalization import gateway_to_channel_message

# Module-level singleton so gateway and worker share one queue instance
job_queue = InMemoryQueue()

app = FastAPI(title="Stratum-4 Gateway", version="0.1.0")


@app.post("/run")
def run(payload: dict[str, Any]) -> dict[str, str]:
    """Accept a job request and return a ``job_id``.

    The payload must be a JSON object (dict).  It is normalized via
    ``gateway_to_channel_message``, wrapped in a ``Job``, registered via the
    ``ControlPlane``, and pushed onto the in-memory queue.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    channel_msg = gateway_to_channel_message(payload)

    # Lazy imports to break the circular dependency chain
    from src.platform.observability.logging import log_job_created
    from src.platform.runtime import create_job
    from src.platform.runtime.control_plane import control_plane

    job = create_job(channel_msg)
    control_plane.register_job(job)
    log_job_created(job)

    job_queue.push(job)

    return {"job_id": job.job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    """Retrieve a job's state and result by its ``job_id``.

    Returns ``404`` with a JSON error body if the job is not found.
    """
    from src.platform.runtime.job_store import job_store  # lazy: break circular import

    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    return {
        "job_id": job.job_id,
        "state": job.state,
        "result": job.result,
    }
