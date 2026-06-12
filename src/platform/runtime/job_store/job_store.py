"""Job store — Stratum-4 runtime.

Abstract interface + in-memory implementation for job persistence.
No orchestration, no lifecycle, no control plane — just save, get,
list, and delete.
"""

from __future__ import annotations

from src.platform.runtime.execution_context import ExecutionContext
from src.platform.runtime.job import Job


class JobStore:
    """Abstract interface for job persistence.

    Implementations must satisfy the following contract:
      - ``save()`` persists or overwrites a job by ``job_id``.
      - ``get()`` returns the job, or ``None`` if not found.
      - ``list()`` returns metadata for all known jobs.
      - ``delete()`` removes a job by ``job_id``.
      - ``__len__()`` returns the number of stored jobs.
    """

    def save(self, job: Job) -> None:
        """Persist *job*, overwriting any existing entry with the same id."""
        raise NotImplementedError

    def get(self, job_id: str) -> Job | None:
        """Retrieve a job by ``job_id``, or ``None`` if not found."""
        raise NotImplementedError

    def list(self) -> list[dict]:
        """Return metadata for all known jobs.

        Each entry should contain at minimum ``job_id`` and ``created_at``.
        """
        raise NotImplementedError

    def delete(self, job_id: str) -> None:
        """Remove a job by ``job_id``.

        Deleting a non-existent job is a no-op.
        """
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError


class InMemoryJobStore(JobStore):
    """In-memory job store backed by a plain dict.

    Intended as a development / test stand-in for a persistent store.
    Checkpoint hydration is simulated via ``to_dict() / from_dict()``
    round-trip on ``get()``.
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
        copy = stored.model_copy(deep=True)
        if copy.execution_context is not None:
            copy.execution_context = ExecutionContext.from_dict(
                copy.execution_context.to_dict()
            )
        return copy

    def list(self) -> list[dict]:
        """Return metadata for all known jobs."""
        return [
            {"job_id": job.job_id, "created_at": job.created_at.isoformat()}
            for job in self._store.values()
        ]

    def delete(self, job_id: str) -> None:
        """Remove a job by ``job_id`` (no-op if missing)."""
        self._store.pop(job_id, None)

    def __len__(self) -> int:
        return len(self._store)


# module-level singleton so gateway, worker, etc. share one store
_default_store = InMemoryJobStore()
