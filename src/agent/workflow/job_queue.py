"""In-memory S4 job queue — stand-in for the Platform job queue.

Sprint 5.1: replaces the stub ``_submit_job()`` in composition_root with
a proper queue that tracks job status (queued → running → completed/failed)
and stores results.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class JobRecord:
    """A single job submission."""

    job_id: str
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    payload: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str | None = None


class InMemoryJobQueue:
    """In-memory S4 job queue with status tracking.

    Used as the ``submit_job_callable`` for the Supervisor and
    ``submit_s4_job`` for the StrategyRouter.  Tests can inspect,
    complete, or fail jobs through the public API.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}

    def submit(self, payload: dict[str, Any]) -> str:
        """Submit a job and return its ``job_id``."""
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        self._jobs[job_id] = JobRecord(job_id=job_id, payload=payload)
        return job_id

    def get(self, job_id: str) -> JobRecord | None:
        """Look up a job by ``job_id``."""
        return self._jobs.get(job_id)

    def list(self, status: str | None = None) -> list[JobRecord]:
        """List all jobs, optionally filtered by *status*."""
        if status is None:
            return list(self._jobs.values())
        return [j for j in self._jobs.values() if j.status == status]

    def mark_running(self, job_id: str) -> None:
        """Transition a job to *running*."""
        self._jobs[job_id].status = "running"

    def mark_complete(self, job_id: str, result: Any = None) -> None:
        """Mark a job as *completed* with an optional result."""
        record = self._jobs[job_id]
        record.status = "completed"
        record.result = result

    def mark_failed(self, job_id: str, error: str) -> None:
        """Mark a job as *failed* with an error message."""
        record = self._jobs[job_id]
        record.status = "failed"
        record.error = error

    def clear(self) -> None:
        """Remove all jobs (useful between tests)."""
        self._jobs.clear()
