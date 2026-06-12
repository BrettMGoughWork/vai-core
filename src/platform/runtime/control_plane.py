"""Control Plane v1 — Stratum-4 runtime.

The authoritative source of truth for job state.  Owns the job registry,
validates all state transitions, and exposes simple orchestration methods.
Synchronous, single-threaded, minimal — no retries, no supervision, no
scheduling, no concurrency.

S4.5.4: The control plane also tracks worker heartbeats via an embedded
:class:`~src.platform.runtime.heartbeat.control_plane.HeartbeatMonitor`.

S4 Supervisor: The control plane optionally hosts a
:class:`~src.platform.supervisor.supervisor_loop.SupervisorLoop` that
monitors worker health and manages lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.platform.runtime.execution_context import ExecutionContext
from src.platform.runtime.heartbeat.control_plane import (
    HeartbeatMonitor,
    HeartbeatStatus,
)
from src.platform.runtime.heartbeat.events import HeartbeatEvent
from src.platform.runtime.job import Job
from src.platform.runtime.job_state import JobState, transition
from src.platform.runtime.job_store import JobStore, job_store as _default_store
from src.platform.runtime.tokens import new_resume_token
from src.platform.supervisor.supervisor_loop import (
    SupervisorLoop,
    WorkerHeartbeat,
)

# ---------------------------------------------------------------------------
# Stratum‑4 isolation: no imports from S1/S2/S3, no queue, no adapter.
# ---------------------------------------------------------------------------


class ControlPlane:
    """Coordinates job lifecycle and state transitions.

    Args:
        job_store: The store that persists job data.  Defaults to the
            module-level ``job_store`` singleton.
        heartbeat_timeout: Seconds before a worker is considered unhealthy.
            ``None`` disables heartbeat tracking (default).
    """

    def __init__(
        self,
        job_store: JobStore | None = None,
        heartbeat_timeout: float | None = None,
        supervisor_loop: SupervisorLoop | None = None,
    ) -> None:
        self.job_store = job_store if job_store is not None else _default_store
        self.heartbeat_monitor: HeartbeatMonitor | None = (
            HeartbeatMonitor(timeout_seconds=heartbeat_timeout)
            if heartbeat_timeout is not None
            else None
        )
        self.supervisor_loop: SupervisorLoop | None = supervisor_loop

    # ------------------------------------------------------------------
    # Heartbeat integration (S4.5.4)
    # ------------------------------------------------------------------

    def accept_heartbeat(
        self,
        event: HeartbeatEvent,
        now: float | None = None,
    ) -> HeartbeatStatus | None:
        """Record a worker heartbeat and return the worker's health status.

        Args:
            event: The heartbeat event emitted by a worker.
            now: Optional current timestamp (defaults to ``event.timestamp``).

        Returns:
            :class:`HeartbeatStatus` if heartbeat tracking is enabled, or
            ``None`` if no ``heartbeat_timeout`` was configured.
        """
        if self.heartbeat_monitor is None:
            return None
        return self.heartbeat_monitor.update(event, now=now)

    def accept_worker_heartbeat(
        self,
        worker_id: str,
        status: str = "healthy",
        job_id: str | None = None,
        now: float | None = None,
    ) -> None:
        """Forward a worker heartbeat to the SupervisorLoop (if configured).

        This is a convenience wrapper that constructs a
        :class:`WorkerHeartbeat` and feeds it to the supervisor.

        Args:
            worker_id: The emitting worker.
            status:    ``"healthy"``, ``"degraded"``, or ``"unresponsive"``.
            job_id:    Optional job being processed.
            now:       Current timestamp; defaults to :func:`time.time`.
        """
        if self.supervisor_loop is None:
            return
        import time as _time

        ts = now if now is not None else _time.time()
        hb = WorkerHeartbeat(
            worker_id=worker_id,
            timestamp=ts,
            status=status,
            job_id=job_id,
        )
        self.supervisor_loop.collect_heartbeat(hb)

    # ------------------------------------------------------------------
    # Resume token helpers
    # ------------------------------------------------------------------

    def issue_resume_token(self, job: Job) -> None:
        """Generate a new resume token for the next cycle and persist.

        Args:
            job: The job to issue a token for.
        """
        job.resume_token = new_resume_token()
        self.save_checkpoint(job)

    # ------------------------------------------------------------------
    # Checkpoint helpers
    # ------------------------------------------------------------------

    def save_checkpoint(self, job: Job) -> None:
        """Persist the job (including its execution context) to the store.

        Args:
            job: The job to persist.
        """
        self.append_lifecycle_event(job, "dehydrate_execution_context")
        self.job_store.save(job)

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

        Asserts that the job is in ``PENDING`` state.  If the job does not
        yet have an ``execution_context``, one is initialised automatically.

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
        if job.execution_context is None:
            job.execution_context = ExecutionContext()
        self.save_checkpoint(job)

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
        self.save_checkpoint(job)

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
        self.save_checkpoint(job)
        self.issue_resume_token(job)

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
        self.save_checkpoint(job)
        self.issue_resume_token(job)

    def mark_poison(self, job: Job, reason: str) -> None:
        """Transition job to ``POISON`` (terminal), attach reason, and persist.

        A poison job has exceeded the maximum consecutive failure threshold
        and must NOT be retried.  The caller (Worker) is responsible for
        moving the job to the dead-letter queue.

        Args:
            job:    The job to mark as poison.
            reason: Human-readable explanation (e.g. "Exceeded 5 failures").

        Raises:
            ValueError: If the current state does not allow the transition.
        """
        old = job.state
        job.state = transition(job.state, JobState.POISON)
        job.result = {"error": reason, "poison": True}
        self._append_trace(job, old, JobState.POISON)
        self.save_checkpoint(job)

    # ------------------------------------------------------------------
    # Cycle trace
    # ------------------------------------------------------------------

    def append_lifecycle_event(
        self, job: Job, event: str, payload: dict | None = None
    ) -> None:
        """Append a lifecycle trace entry to the job's trace.

        Lifecycle events record hydration/dehydration of the execution
        context at the runtime level.

        Args:
            job:    The job whose trace to extend.
            event:  The lifecycle event name
                    (e.g. ``"hydrate_execution_context"``).
            payload: Optional metadata dict for the entry.
        """
        job.trace.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "payload": payload or {},
            }
        )
        self.job_store.save(job)

    def append_cycle_trace(self, job: Job, event: str, payload: dict) -> None:
        """Append a cycle trace entry to the job's execution context.

        Args:
            job:    The job whose cycle trace to extend.
            event:  The cycle event name (e.g. ``"cycle_start"``).
            payload: Arbitrary metadata dict for the entry.
        """
        if job.execution_context is None:
            job.execution_context = ExecutionContext()
        job.execution_context.cycle_trace.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "payload": payload,
            }
        )
        self.save_checkpoint(job)


# Module-level singleton so gateway and worker share one control plane
control_plane = ControlPlane()
