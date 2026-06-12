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
from src.platform.runtime.job_state import JobState
from src.platform.runtime.recovery.crash_recovery import (
    CrashRecovery,
    RecoveryContext,
    default_crash_recovery,
)
from src.platform.runtime.retry.tool_wrapper import (
    PoisonInstruction,
    RetryInstruction,
    ToolRetryWrapper,
)
from src.platform.runtime.retry.poison import default_poison_detector
from src.platform.runtime.safety.panic_guard import (
    PanicDecision,
    PanicGuard,
    default_panic_guard,
)
from src.platform.runtime.safety.degraded_mode import (
    DegradedContext,
    DegradedMode,
    default_degraded_mode,
)
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
        crash_recovery: CrashRecovery | None = None,
    ) -> None:
        self._queue = queue
        self._cp = control_plane
        self.timeout_seconds = timeout_seconds
        self._retry_wrapper = ToolRetryWrapper(
            execute_job_payload,
            poison_detector=default_poison_detector(),
        )
        self._crash_recovery = (
            crash_recovery if crash_recovery is not None
            else default_crash_recovery()
        )
        self._panic_guard = default_panic_guard()
        self._degraded_mode = default_degraded_mode()

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

        # Reload from store and hydrate persisted fields (checkpoint load)
        stored = self._cp.job_store.get(job.job_id)
        if stored is not None:
            if stored.execution_context is not None:
                job.execution_context = stored.execution_context
            if stored.resume_token is not None:
                job.resume_token = stored.resume_token
            job.failure_count = stored.failure_count

        # Record hydration event
        self._cp.append_lifecycle_event(
            job, "hydrate_execution_context",
        )

        # ---- Crash recovery check -------------------------------------------
        recovery_ctx = RecoveryContext(
            job_id=job.job_id,
            last_checkpoint=job.execution_context,
            last_resume_token=job.resume_token,
            job_state=job.state.value,
        )
        recovery_decision = self._crash_recovery.evaluate(recovery_ctx)

        if recovery_decision.should_recover:
            # Job was left in RUNNING state by a crashed worker.
            # Keep existing state, resume token, and checkpoint.
            # Do NOT mark_running (already RUNNING).
            # Do NOT issue a new resume token.
            self._cp.append_lifecycle_event(
                job, "crash_recovery",
                {"reason": recovery_decision.reason},
            )
            job.crash_count += 1
        elif job.state == JobState.POISON:
            # Poison jobs are dead — return them as-is
            self._cp.append_lifecycle_event(
                job, "poison_skip",
                {"reason": "Job is POISON — skipping execution"},
            )
            return job
        else:
            # Normal path: ensure resume token and transition to RUNNING
            if job.resume_token is None:
                self._cp.issue_resume_token(job)
            self._cp.mark_running(job)
            log_job_started(job)

        # ---- Idempotency validation -------------------------------------------
        # Ensure the resume token we hold matches the stored checkpoint.
        # A mismatch means a crash occurred between checkpoint and execution;
        # in that case, re-hydrate from the stored checkpoint.
        if stored is not None and stored.resume_token is not None:
            if not self._crash_recovery.validate_resume_token(
                stored.resume_token, job.resume_token,
            ):
                # Re-hydrate from stored checkpoint for consistent state
                job.execution_context = stored.execution_context
                job.resume_token = stored.resume_token
                self._cp.append_lifecycle_event(
                    job, "idempotency_recovery",
                    {"reason": "Resume token mismatch — re-hydrated from checkpoint"},
                )

        # ---- Degraded mode check --------------------------------------------
        # Before the multi-cycle loop, retry exhaustion has not been evaluated
        # yet — only cumulative statistics are meaningful here.
        degraded_ctx = DegradedContext(
            consecutive_failures=job.consecutive_failures,
            panic_count=job.panic_count,
            crash_count=job.crash_count,
            retry_exhausted=False,
        )
        degraded_decision = self._degraded_mode.evaluate(degraded_ctx)

        if degraded_decision.enter_degraded:
            # Skip S1/S2 execution — produce safe fallback
            job.result = {
                "output": None,
                "error": None,
                "fallback": True,
                "reason": degraded_decision.reason,
            }
            self._cp.mark_succeeded(job, job.result)
            self._cp.save_checkpoint(job)
            log_job_finished(job)
            return job

        # ---- Multi-cycle loop ------------------------------------------------
        done = False
        attempt = 1
        while not done:
            self._cp.append_cycle_trace(job, "cycle_start", {})

            @self._panic_guard.wrap
            def run_cycle():
                return self._retry_wrapper.execute(
                    payload=job.payload,
                    execution_context=job.execution_context.to_dict()
                    if job.execution_context
                    else None,
                    resume_token=job.resume_token,
                    attempt=attempt,
                    job_id=job.job_id,
                    failure_count=job.failure_count,
                )

            output = run_cycle()

            # Panic check — unexpected exception caught by PanicGuard
            if isinstance(output, PanicDecision) and output.is_panic:
                job.panic_count += 1
                job.consecutive_failures += 1
                self._cp.mark_failed(
                    job,
                    {
                        "error_type": output.safe_failure.error_type,
                        "message": output.safe_failure.message,
                    },
                )
                self._cp.save_checkpoint(job)
                log_job_finished(job)
                return job

            # Check for poison instruction
            if isinstance(output, PoisonInstruction):
                job.failure_count += 1
                job.consecutive_failures += 1
                poison_reason = output.reason
                self._cp.mark_poison(job, poison_reason)
                log_job_finished(job)
                return job

            # Check for retry instruction
            if isinstance(output, RetryInstruction):
                job.failure_count += 1
                job.consecutive_failures += 1
                time.sleep(output.delay_seconds)
                attempt = output.next_attempt
                self._cp.append_cycle_trace(
                    job, "cycle_end",
                    {"done": False, "retry": True,
                     "delay": output.delay_seconds, "attempt": attempt - 1},
                )
                self._cp.save_checkpoint(job)
                self._cp.issue_resume_token(job)
                continue

            # Reset failure counts on successful cycle
            job.failure_count = 0
            job.consecutive_failures = 0

            # Update ExecutionContext from output
            if job.execution_context is not None:
                job.execution_context.cognitive_state = output.get(
                    "cognitive_state", {}
                )
                job.execution_context.memory = output.get("memory", {})
                job.execution_context.last_result = output.get("result")

            # Check done flag — reset attempt on success
            done = bool(output.get("done", False))
            attempt = 1

            # End-of-cycle trace + checkpoint
            self._cp.append_cycle_trace(job, "cycle_end", {"done": done})
            self._cp.save_checkpoint(job)
            self._cp.issue_resume_token(job)

        # ---- Loop complete ---------------------------------------------------
        self._cp.mark_succeeded(job, job.execution_context.last_result)
        self._cp.save_checkpoint(job)
        log_job_finished(job)
        return job
