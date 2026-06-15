"""Worker v1 — Stratum-4 runtime.

Pops ``Job``\\s from the queue, runs them through a composable pipeline
(pre-flight checks → multi-cycle execution loop), and returns the updated
job.  The pipeline abstraction keeps the worker lean as more stages are
added by S4.5–S4.8.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from src.platform.observability.logging import log_execution, log_supervisor_action as _log_supervisor_action
from src.platform.observability.metrics import emit_metric
from src.platform.observability.tracing import (
    emit_cycle_trace as _emit_cycle_trace,
    emit_segment_trace as _emit_segment_trace,
)
from src.platform.queue.queue import Queue
from src.gateway.channels.registry import ChannelRegistry
from src.platform.runtime.control_plane import ControlPlane
from src.platform.runtime.execution_context import ExecutionContext
from src.platform.runtime.job import Job
from src.platform.runtime.job_state import JobState
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

WorkExecutor = Callable[..., dict[str, Any]]
"""Signature: ``(payload, execution_context=None, resume_token=None, **kwargs) -> dict``.

Implementations process a job payload and return a result dict containing
at minimum an ``output`` key (for channel response routing).
"""


class Worker:
    """Processes one job per ``process_next()`` call.

    The worker is a generic durable execution engine.  It does **not** know
    about S1 (LLM), S2 (planner), or S3 (capabilities).  Work is delegated
    to the injected ``executor`` callable, which the caller provides.

    Args:
        executor:          Callable that processes job payloads.  Receives
                           ``(payload, execution_context=None, resume_token=None,
                           **kwargs)`` and must return a ``dict`` with at
                           least an ``output`` key (for channel routing).
        queue:             The queue to poll for pending jobs.
        control_plane:     The ``ControlPlane`` that owns job state transitions.
        timeout_seconds:   Timeout (seconds) for a single execution attempt.
        crash_recovery:    Optional custom ``CrashRecovery`` evaluator.
        channel_registry:  Optional ``ChannelRegistry`` for routing job
                           responses back to the originating channel.
    """

    def __init__(
        self,
        executor: WorkExecutor,
        queue: Queue,
        control_plane: ControlPlane,
        timeout_seconds: int = 5,
        crash_recovery: CrashRecovery | None = None,
        channel_registry: ChannelRegistry | None = None,
    ) -> None:
        self._executor = executor
        self._queue = queue
        self._cp = control_plane
        self.timeout_seconds = timeout_seconds
        self._channel_registry = channel_registry
        self._retry_wrapper = ToolRetryWrapper(
            self._executor,
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

    def _route_response(self, job: Job) -> None:
        """Route the result of a completed job back to the originating channel.

        If the job completed successfully and a ``ChannelRegistry`` has been
        configured, looks up ``job.payload.channel`` and calls its ``send()``
        method with the result text.
        """
        if self._channel_registry is None:
            return
        if job.state is not JobState.SUCCEEDED or job.result is None:
            return

        channel_name = getattr(job.payload, "channel", None)
        if not channel_name:
            return

        channel = self._channel_registry.get(channel_name)
        if channel is None:
            return

        # Extract the output text from the executor result dict.
        # The executor contract requires an ``output`` key for channel routing.
        result: dict[str, Any] = job.result
        response_text = result.get("output", "")

        if response_text:
            channel.send({"output": response_text, "metadata": {}})

    def process_next(self) -> Job | None:
        """Pop the next job, run the pipeline, and return the updated job.

        Steps:
            1. Pop a ``Job`` from the queue — return ``None`` if empty.
            2. Reload from the ``JobStore`` and hydrate persisted fields
               (``ExecutionContext``, resume token, failure count).
            3. Run the composable pipeline — each stage either returns the
               ``Job`` (abort or completion) or lets the pipeline continue.
            4. Route the result back to the originating channel (if
               configured).
            5. Return the updated ``Job``.

        Returns:
            The updated ``Job``, or ``None`` if the queue was empty.
        """
        job = self._queue.pop()
        if job is None:
            return None

        # Reload from store and hydrate persisted fields (checkpoint load)
        stored = self._cp.job_store.get(job.job_id)
        attempt = job.failure_count + 1
        cycle_trace_id = _emit_cycle_trace(
            job.job_id, str(id(self)), attempt, "start",
            component="worker",
        )

        if stored is not None:
            if stored.execution_context is not None:
                job.execution_context = stored.execution_context
            if stored.resume_token is not None:
                job.resume_token = stored.resume_token
            job.failure_count = stored.failure_count

        self._cp.append_lifecycle_event(
            job, "hydrate_execution_context",
        )

        # Run the composable pipeline with execution timing
        t0 = time.monotonic()
        _emit_segment_trace(
            job.job_id, "pipeline", "start",
            component="worker", parent_trace_id=cycle_trace_id,
        )
        ctx = PipelineContext(
            job=job,
            control_plane=self._cp,
            stored_job=stored,
        )
        try:
            updated_job = self._pipeline.run(ctx)
        except Exception as exc:
            # Unexpected crash outside pipeline stages — mark as failed.
            # Ensure the job is at least RUNNING so the transition is valid.
            if job.state is JobState.PENDING:
                self._cp.mark_running(job)
            emit_metric("s4.repair.count", 1, {"repairtype": "panicrecovery"})
            _emit_segment_trace(
                job.job_id, "pipeline", "repair",
                component="worker", parent_trace_id=cycle_trace_id,
                extra_fields={"error": type(exc).__name__},
            )
            self._cp.mark_failed(
                job,
                {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            )
            self._cp.save_checkpoint(job)
            updated_job = job
            _log_supervisor_action(
                "panicrecovery",
                f"Pipeline crash — {type(exc).__name__} in job {job.job_id}",
                worker_id=str(id(self)),
                job_id=job.job_id,
            )
            # Local import to avoid circular dependency at module level
            from src.platform.supervisor.system_alerts import alert_async as _alert  # fmt: skip
            _alert(
                severity="critical",
                source="worker",
                summary=f"Pipeline crash — {type(exc).__name__} in job {job.job_id}",
                details=f"Worker {str(id(self))} crashed processing job {job.job_id}: {exc}",
                metadata={
                    "worker_id": str(id(self)),
                    "job_id": job.job_id,
                    "error_type": type(exc).__name__,
                },
            )

        elapsed_ms = (time.monotonic() - t0) * 1000.0

        _emit_segment_trace(
            updated_job.job_id, "pipeline", "end",
            component="worker", parent_trace_id=cycle_trace_id,
            extra_fields={"duration_ms": str(int(elapsed_ms))},
        )

        cycle_action = "end" if updated_job.state is JobState.SUCCEEDED else "retry"
        _emit_cycle_trace(
            updated_job.job_id, str(id(self)), attempt, cycle_action,
            duration_ms=int(elapsed_ms),
            component="worker", parent_trace_id=cycle_trace_id,
        )

        job_type = getattr(updated_job.payload, "channel", "unknown")
        emit_metric(
            "s4.job.executiontimems",
            elapsed_ms,
            {
                "workerid": str(id(self)),
                "jobtype": str(job_type),
            },
        )
        log_execution(str(id(self)), str(job_type), int(elapsed_ms))

        # Emit worker health on successful completion
        if updated_job.state is JobState.SUCCEEDED:
            emit_metric("s4.worker.health", 1, {
                "worker_id": str(id(self)),
                "status": "healthy",
            })

        # Route the response back to the originating channel
        self._route_response(updated_job)

        return updated_job
