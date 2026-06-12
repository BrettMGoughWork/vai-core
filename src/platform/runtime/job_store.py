"""Job store — Stratum-4 runtime.

In-memory ``dict[str, Job]`` store for job persistence during the
Minimal Execution Path.  No orchestration, no lifecycle, no control
plane — just save and get.

Checkpoint contract:
  - ``save()`` persists the job including its execution context.
  - ``get()`` hydrates a fresh ``ExecutionContext`` from the stored
    serialised dict, so the caller receives an independent copy.
"""

from __future__ import annotations

from src.platform.runtime.execution_context import ExecutionContext
from src.platform.runtime.job import Job


class JobStore:
    """In-memory job store backed by a plain dict.

    Intended as a development / test stand-in for a persistent store
    (PostgreSQL, Redis, etc.).  Checkpoint hydration is simulated via
    ``to_dict() / from_dict()`` round-trip on ``get()``.
    """

    def __init__(self) -> None:
        self._store: dict[str, Job] = {}

    def save(self, job: Job) -> None:
        """Store or overwrite a job by its ``job_id``."""
        self._store[job.job_id] = job

    def get(self, job_id: str) -> Job | None:
        """Retrieve a job by its ``job_id``, or ``None`` if not found.

        Returns a **deep copy** of the stored job so that callers receive
        an independent instance.  The execution context is also hydrated
        via a serialisation round-trip inside the copy, simulating
        checkpoint load from a persistent store.
        """
        stored = self._store.get(job_id)
        if stored is None:
            return None
        # Deep copy so the caller cannot mutate the stored original
        copy = stored.model_copy(deep=True)
        if copy.execution_context is not None:
            copy.execution_context = ExecutionContext.from_dict(
                copy.execution_context.to_dict()
            )
        return copy

    def __len__(self) -> int:
        return len(self._store)


# module-level singleton so gateway, worker, etc. share one store
job_store = JobStore()
