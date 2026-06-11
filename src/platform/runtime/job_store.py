"""Job store — Stratum-4 runtime.

In-memory ``dict[str, Job]`` store for job persistence during the
Minimal Execution Path.  No orchestration, no lifecycle, no control
plane — just save and get.
"""

from __future__ import annotations

from src.platform.runtime.job import Job


class JobStore:
    """In-memory job store backed by a plain dict.

    Intended as a development / test stand-in for a persistent store
    (PostgreSQL, Redis, etc.).
    """

    def __init__(self) -> None:
        self._store: dict[str, Job] = {}

    def save(self, job: Job) -> None:
        """Store or overwrite a job by its ``job_id``."""
        self._store[job.job_id] = job

    def get(self, job_id: str) -> Job | None:
        """Retrieve a job by its ``job_id``, or ``None`` if not found."""
        return self._store.get(job_id)

    def __len__(self) -> int:
        return len(self._store)


# module-level singleton so gateway, worker, etc. share one store
job_store = JobStore()
