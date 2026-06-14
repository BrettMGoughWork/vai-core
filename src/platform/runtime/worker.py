"""Worker v1 — Stratum-4 runtime.

Pops ``Job``\\s from the queue, runs them through a composable pipeline
(pre-flight checks → multi-cycle execution loop), and returns the updated
job.  The pipeline abstraction keeps the worker lean as more stages are
added by S4.5–S4.8.
"""

from __future__ import annotations

import time
from typing import Any

from src.platform.adapter.adapter import s1_to_s2_adapter, s2_to_s1_adapter
from src.platform.observability.logging import log_execution, log_supervisor_action as _log_supervisor_action
from src.platform.observability.metrics import emit_metric
from src.platform.observability.tracing import (
    emit_cycle_trace as _emit_cycle_trace,
    emit_segment_trace as _emit_segment_trace,
)
from src.platform.queue.queue import Queue
from src.platform.runtime.channels.registry import ChannelRegistry
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
from src.platform.transport.normalization import ChannelMessage
from src.strategy.planning.s1_contract.s1_client import call_s1_backend
from src.strategy.planning.s1_contract.s1_real_client import ENABLE_REAL_LLM
from src.strategy.planning.s1_contract.types import (
    PromptRequest,
    PromptResponse,
    S1Error,
)


def _dispatch_to_s1(
    payload: ChannelMessage,
    s1_request: dict[str, Any],
    enable_real_llm: bool = False,
) -> dict[str, Any]:
    """Dispatch a job payload to the S1 cognitive stratum.

    Builds a :class:`PromptRequest` from the channel message and sends it
    through ``call_s1_backend()`` (simulation or real_llm backend).

    Args:
        payload:         The original ``ChannelMessage`` from the channel.
        s1_request:      The S1 request dict from ``s2_to_s1_adapter``.
        enable_real_llm: If ``True``, request the real LLM backend (subject
                         to the upstream kill-switch in ``s1_real_client``).

    Returns:
        A raw output dict compatible with ``s1_to_s2_adapter``.
    """
    # Extract the user's input text from the normalized payload structure.
    # ChannelMessage.input is a dict with fields like
    # {"input": "<user text>", "metadata": {...}}.
    raw_input: dict[str, Any] = payload.input
    user_text: str = ""
    if isinstance(raw_input, dict):
        user_text = raw_input.get("input", "")
        if not isinstance(user_text, str):
            user_text = str(user_text)

    request = PromptRequest(
        prompt={"instruction": user_text},
        memory={},
        plan_context={},
        tool_context=[
            {
                "name": "chat",
                "description": "Respond to the user's message",
                "schema": {
                    "type": "object",
                    "properties": {"response": {"type": "string"}},
                },
            },
        ],
    )

    backend = "real_llm" if enable_real_llm else "simulation"
    result = call_s1_backend(request, backend=backend)

    if isinstance(result, S1Error):
        return {
            "error": result.message,
            "error_type": result.type,
            "s1_request": s1_request.get("input", {}),
        }

    # PromptResponse — extract the structured output
    return {
        "s1_output": result.output,
        "s1_request": s1_request.get("input", {}),
    }


def execute_job_payload(
    payload: ChannelMessage,
    execution_context: dict | None = None,
    resume_token: str | None = None,
) -> dict[str, Any]:
    """Execute one cognitive cycle through the adapter pipeline.

    Converts the S4 payload to an S1 request via the S2→S1 adapter,
    executes against the cognitive strata via S1 dispatch (simulation
    or real LLM), normalises the raw output via the S1→S2 adapter,
    and wraps the result in a multi-cycle envelope
    ``{done, cognitive_state, memory, result}``.

    Args:
        payload:          The job payload (a ``ChannelMessage``).
        execution_context: Opaque cognitive context (unused in stub).
        resume_token:     Opaque cycle identifier (passthrough).

    Returns:
        A dict with keys ``done``, ``cognitive_state``, ``memory``,
        and ``result``.
    """
    s1_request = s2_to_s1_adapter(payload, resume_token=resume_token)
    raw_output = _dispatch_to_s1(
        payload, s1_request, enable_real_llm=ENABLE_REAL_LLM
    )
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
        queue:             The queue to poll for pending jobs.
        control_plane:     The ``ControlPlane`` that owns job state transitions.
        timeout_seconds:   Timeout (seconds) for a single execution attempt.
        crash_recovery:    Optional custom ``CrashRecovery`` evaluator.
        channel_registry:  Optional ``ChannelRegistry`` for routing job
                           responses back to the originating channel.
    """

    def __init__(
        self,
        queue: Queue,
        control_plane: ControlPlane,
        timeout_seconds: int = 5,
        crash_recovery: CrashRecovery | None = None,
        channel_registry: ChannelRegistry | None = None,
    ) -> None:
        self._queue = queue
        self._cp = control_plane
        self.timeout_seconds = timeout_seconds
        self._channel_registry = channel_registry
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

        # Extract the S1 output text from the result envelope.
        # The result structure is:
        #   {..., "result": {"type": "s2_result", "output": {"s1_output": {...}}}}
        result: dict[str, Any] = job.result
        s2_result = result.get("result", {})
        if not isinstance(s2_result, dict):
            return
        s1_output: dict[str, Any] = s2_result.get("output", {}).get("s1_output", {})

        # PromptResponse.output is a dict with keys like drift, reflection, etc.
        # Try to extract a human-readable summary; fall back to the first string
        # value found.
        response_text: str = ""
        if isinstance(s1_output, dict):
            # Prefer 'reflection' as it contains the simulator's main response
            response_text = s1_output.get("reflection", "")
            if not response_text:
                # Fall back to any non-empty string value
                for val in s1_output.values():
                    if isinstance(val, str) and val.strip():
                        response_text = val
                        break
        elif isinstance(s1_output, str):
            response_text = s1_output

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
