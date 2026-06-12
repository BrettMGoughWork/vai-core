"""Control Plane v1 — Stratum-4 runtime.

The authoritative source of truth for job state.  Owns the job registry,
validates all state transitions, and exposes simple orchestration methods.
Synchronous, single-threaded, minimal — no retries, no supervision, no
scheduling, no concurrency.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.platform.runtime.job import Job
from src.platform.runtime.job_state import JobState, transition
from src.platform.runtime.job_store import JobStore, job_store as _default_store


class ControlPlane:
    """Coordinates job lifecycle and state transitions.

    Args:
        job_store: The store that persists job data.  Defaults to the
            module-level ``job_store`` singleton.
    """

    def __init__(self, job_store: JobStore | None = None) -> None:
        self.job_store = job_store if job_store is not None else _default_store

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def _append_trace(
        self, job: Job, from_state: JobState, to_state: JobState
    ) -> None:
        """Append a state-transition trace entry to the job.

        Args:
            job:        The job whose trace to extend.
            from_state: The state before the transition.
            to_state:   The state after the transition.
        """
        job.trace.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "state_transition",
                "from": from_state.value,
                "to": to_state.value,
            }
        )

    def register_job(self, job: Job) -> None:
        """Persist a newly created job.

        Asserts that the job is in ``PENDING`` state.

        Args:
            job: A freshly created ``Job`` (must be ``state == PENDING``).

        Raises:
            ValueError: If the job is not in ``PENDING``.
        """
        if job.state is not JobState.PENDING:
            raise ValueError(
                f"Cannot register job in state {job.state.value!r}; "
                f"must be {JobState.PENDING.value!r}"
            )
        self.job_store.save(job)

    def mark_running(self, job: Job) -> None:
        """Transition job to ``RUNNING`` and persist.

        Args:
            job: The job to update.

        Raises:
            ValueError: If the current state does not allow the transition.
        """
        old = job.state
        job.state = transition(job.state, JobState.RUNNING)
        self._append_trace(job, old, JobState.RUNNING)
        self.job_store.save(job)

    def mark_succeeded(self, job: Job, result: dict) -> None:
        """Transition job to ``SUCCEEDED``, attach the result, and persist.

        Args:
            job:    The job to update.
            result: The execution result dict.

        Raises:
            ValueError: If the current state does not allow the transition.
        """
        old = job.state
        job.state = transition(job.state, JobState.SUCCEEDED)
        job.result = result
        self._append_trace(job, old, JobState.SUCCEEDED)
        self.job_store.save(job)

    def mark_failed(self, job: Job, error: dict) -> None:
        """Transition job to ``FAILED``, attach the structured error, and persist.

        Args:
            job:   The job to update.
            error: A structured error dict (e.g. ``{"error_type": ..., "message": ...}``).

        Raises:
            ValueError: If the current state does not allow the transition.
        """
        old = job.state
        job.state = transition(job.state, JobState.FAILED)
        job.result = error
        self._append_trace(job, old, JobState.FAILED)
        self.job_store.save(job)


# Module-level singleton so gateway and worker share one control plane
control_plane = ControlPlane()
