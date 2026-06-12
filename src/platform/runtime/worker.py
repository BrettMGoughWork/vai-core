"""Worker v1 — Stratum-4 runtime.

Pops ``Job``\\s from the queue, runs them through a composable pipeline
(pre-flight checks → multi-cycle execution loop), and returns the updated
job.  The pipeline abstraction keeps the worker lean as more stages are
added by S4.5–S4.8.
"""

from __future__ import annotations

from typing import Any

from src.platform.adapter.adapter import s1_to_s2_adapter, s2_to_s1_adapter
from src.platform.queue.queue import Queue
from src.platform.runtime.control_plane import ControlPlane
from src.platform.runtime.execution_context import ExecutionContext
from src.platform.runtime.job import Job
from src.platform.runtime.pipeline import (
    CrashRecoveryStage,
    DegradedModeStage,
    EvaluatorPipeline,
    ExecutionStage,
    IdempotencyStage,
    PipelineContext,
)
from src.platform.runtime.recovery.crash_recovery import (
    CrashRecovery,
    default_crash_recovery,
)
from src.platform.runtime.retry.tool_wrapper import ToolRetryWrapper
from src.platform.runtime.retry.poison import default_poison_detector
from src.platform.runtime.safety.panic_guard import (
    PanicGuard,
    default_panic_guard,
)
from src.platform.runtime.safety.degraded_mode import (
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
        timeout_seconds:  Timeout (seconds) for a single execution attempt.
        crash_recovery:  Optional custom ``CrashRecovery`` evaluator.
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

        # Build composable pipeline
        self._pipeline = EvaluatorPipeline([
            CrashRecoveryStage(self._crash_recovery),
            IdempotencyStage(self._crash_recovery),
            DegradedModeStage(self._degraded_mode),
            ExecutionStage(
                self._retry_wrapper,
                self._panic_guard,
                self.timeout_seconds,
            ),
        ])

    def process_next(self) -> Job | None:
        """Pop the next job, run the pipeline, and return the updated job.

        Steps:
            1. Pop a ``Job`` from the queue — return ``None`` if empty.
            2. Reload from the ``JobStore`` and hydrate persisted fields
               (``ExecutionContext``, resume token, failure count).
            3. Run the composable pipeline — each stage either returns the
               ``Job`` (abort or completion) or lets the pipeline continue.
            4. Return the updated ``Job``.

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

        self._cp.append_lifecycle_event(
            job, "hydrate_execution_context",
        )

        # Run the composable pipeline
        ctx = PipelineContext(
            job=job,
            control_plane=self._cp,
            stored_job=stored,
        )
        return self._pipeline.run(ctx)
