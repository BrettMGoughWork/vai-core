"""Worker v1 — Stratum-4 runtime.

The simplest possible worker loop: pop a ``Job`` from the queue, call the S4→S1
adapter to prepare the request, execute against the cognitive strata (stubbed),
call the S1→S2 adapter to normalise the output, and update state via the
``ControlPlane``.  No concurrency, no retries, no lifecycle.
"""

from __future__ import annotations

import time
from typing import Any

from src.platform.adapter.adapter import s1_to_s2_adapter, s2_to_s1_adapter
from src.platform.observability.logging import log_job_started, log_job_finished
from src.platform.queue.queue import Queue
from src.platform.runtime.control_plane import ControlPlane
from src.platform.runtime.execution_context import ExecutionContext
from src.platform.runtime.job import Job
from src.platform.transport.normalization import ChannelMessage


def _mock_execute(s1_request: dict[str, Any]) -> dict[str, Any]:
    """Temporary: stand-in for real S1 dispatch.

    Once S1 is wired, this function will be replaced by the actual S1
    execution path.  For now it echoes the input back as raw output.
    """
    return {"echo": s1_request.get("input", {})}


def execute_job_payload(
    payload: ChannelMessage,
    execution_context: dict | None = None,
    resume_token: str | None = None,
) -> dict[str, Any]:
    """Execute one cognitive cycle through the adapter pipeline.

    Converts the S4 payload to an S1 request via the S2→S1 adapter,
    executes against the cognitive strata, normalises the raw output
    via the S1→S2 adapter, and wraps the result in a multi-cycle
    envelope ``{done, cognitive_state, memory, result}``.

    Args:
        payload:          The job payload (a ``ChannelMessage``).
        execution_context: Opaque cognitive context (unused in stub).
        resume_token:     Opaque cycle identifier (passthrough).

    Returns:
        A dict with keys ``done``, ``cognitive_state``, ``memory``,
        and ``result``.
    """
    s1_request = s2_to_s1_adapter(payload, resume_token=resume_token)
    raw_output = _mock_execute(s1_request)
    s2_result = s1_to_s2_adapter(raw_output)

    return {
        "done": True,
        "cognitive_state": {},
        "memory": {},
        "result": s2_result,
    }


class Worker:
    """Processes one job per ``process_next()`` call.

    Args:
        queue:          The queue to poll for pending jobs.
        control_plane:  The ``ControlPlane`` that owns job state transitions.
    """

    def __init__(
        self,
        queue: Queue,
        control_plane: ControlPlane,
        timeout_seconds: int = 5,
    ) -> None:
        self._queue = queue
        self._cp = control_plane
        self.timeout_seconds = timeout_seconds

    def process_next(self) -> Job | None:
        """Pop the next job and execute multi-cycle loop.

        The multi-cycle loop:
            1. Pop a ``Job`` from the queue.
            2. If the queue is empty, return ``None``.
            3. Reload from store — hydrate ``ExecutionContext`` and resume token.
            4. ``ControlPlane.mark_running()``.
            5. Enter ``while not done`` loop:
               a. ``append_cycle_trace("cycle_start")``.
               b. ``execute_job_payload()`` — runs the adapter pipeline.
               c. Update ``ExecutionContext`` from output.
               d. Check ``done`` flag.
               e. ``append_cycle_trace("cycle_end")``.
               f. ``save_checkpoint()`` + ``issue_resume_token()``.
            6. ``ControlPlane.mark_succeeded()``.
            7. Return the updated ``Job``.

        Returns:
            The updated ``Job``, or ``None`` if the queue was empty.
        """
        job = self._queue.pop()
        if job is None:
            return None

        # Reload from store and hydrate execution context (checkpoint load)
        stored = self._cp.job_store.get(job.job_id)
        if stored is not None:
            if stored.execution_context is not None:
                job.execution_context = stored.execution_context
            if stored.resume_token is not None:
                job.resume_token = stored.resume_token

        # Record hydration event
        self._cp.append_lifecycle_event(
            job, "hydrate_execution_context",
        )

        # Ensure a resume token exists for this cycle
        if job.resume_token is None:
            self._cp.issue_resume_token(job)

        self._cp.mark_running(job)
        log_job_started(job)

        # ---- Multi-cycle loop ------------------------------------------------
        done = False
        while not done:
            self._cp.append_cycle_trace(job, "cycle_start", {})

            try:
                output = execute_job_payload(
                    payload=job.payload,
                    execution_context=job.execution_context.to_dict()
                    if job.execution_context
                    else None,
                    resume_token=job.resume_token,
                )
            except Exception as e:
                self._cp.mark_failed(
                    job,
                    {"error_type": type(e).__name__, "message": str(e)},
                )
                self._cp.save_checkpoint(job)
                log_job_finished(job)
                return job

            # Update ExecutionContext from output
            if job.execution_context is not None:
                job.execution_context.cognitive_state = output.get(
                    "cognitive_state", {}
                )
                job.execution_context.memory = output.get("memory", {})
                job.execution_context.last_result = output.get("result")

            # Check done flag
            done = bool(output.get("done", False))

            # End-of-cycle trace + checkpoint
            self._cp.append_cycle_trace(job, "cycle_end", {"done": done})
            self._cp.save_checkpoint(job)
            self._cp.issue_resume_token(job)

        # ---- Loop complete ---------------------------------------------------
        self._cp.mark_succeeded(job, job.execution_context.last_result)
        self._cp.save_checkpoint(job)
        log_job_finished(job)
        return job
