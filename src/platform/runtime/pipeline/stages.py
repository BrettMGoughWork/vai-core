"""Concrete pipeline stages for the S4 worker."""

from __future__ import annotations

import time
from typing import Any

from src.platform.observability.logging import log_job_finished, log_job_started
from src.platform.observability.metrics import emit_metric
from src.platform.runtime.job import Job
from src.platform.runtime.job_state import JobState
from src.platform.runtime.pipeline.base import PipelineContext, PipelineStage
from src.platform.runtime.recovery.crash_recovery import (
    CrashRecovery,
    RecoveryContext,
)
from src.platform.runtime.retry.tool_wrapper import (
    PoisonInstruction,
    RetryInstruction,
    ToolRetryWrapper,
)
from src.platform.runtime.safety.degraded_mode import (
    DegradedContext,
    DegradedDecision,
    DegradedMode,
    SafeFallbackOutput,
    SignalState,
    WorkerDegradedEvent,
    WorkerRecoveredEvent,
)
from src.platform.runtime.safety.panic_guard import PanicDecision, PanicGuard


# ---------------------------------------------------------------------------
# Stage 1 — Crash recovery + poison gate + normal initialisation
# ---------------------------------------------------------------------------


class CrashRecoveryStage(PipelineStage):
    """Evaluates crash recovery, gates poison jobs, and sets up normal execution.

    Order of checks (matches pre-refactor ``process_next`` semantics):

    1. If ``CrashRecovery.evaluate()`` says *should_recover* → log event,
       increment ``crash_count``, and continue without ``mark_running``.
    2. If job is in ``POISON`` state → return the job immediately (abort).
    3. Otherwise → issue resume token, ``mark_running``, ``log_job_started``.
    """

    def __init__(self, crash_recovery: CrashRecovery) -> None:
        self._crash_recovery = crash_recovery

    @property
    def name(self) -> str:
        return "crash_recovery"

    def evaluate(self, ctx: PipelineContext) -> Job | None:
        job = ctx.job
        cp = ctx.control_plane

        recovery_ctx = RecoveryContext(
            job_id=job.job_id,
            last_checkpoint=job.execution_context,
            last_resume_token=job.resume_token,
            job_state=job.state.value,
        )
        recovery_decision = self._crash_recovery.evaluate(recovery_ctx)

        if recovery_decision.should_recover:
            cp.append_lifecycle_event(
                job,
                "crash_recovery",
                {"reason": recovery_decision.reason},
            )
            job.crash_count += 1
        elif job.state == JobState.POISON:
            cp.append_lifecycle_event(
                job,
                "poison_skip",
                {"reason": "Job is POISON — skipping execution"},
            )
            return job
        else:
            if job.resume_token is None:
                cp.issue_resume_token(job)
            cp.mark_running(job)
            log_job_started(job)

        return None


# ---------------------------------------------------------------------------
# Stage 2 — Idempotency (resume-token validation)
# ---------------------------------------------------------------------------


class IdempotencyStage(PipelineStage):
    """Validates the resume token against the stored checkpoint.

    A mismatch between ``job.resume_token`` (potentially just issued by
    ``CrashRecoveryStage``) and the persisted token means a crash occurred
    between checkpoint and execution.  When that happens, re-hydrate the
    execution context and resume token from the stored checkpoint.
    """

    def __init__(self, crash_recovery: CrashRecovery) -> None:
        self._crash_recovery = crash_recovery

    @property
    def name(self) -> str:
        return "idempotency"

    def evaluate(self, ctx: PipelineContext) -> Job | None:
        job = ctx.job
        cp = ctx.control_plane
        stored = ctx.stored_job

        if stored is not None and stored.resume_token is not None:
            if not self._crash_recovery.validate_resume_token(
                stored.resume_token,
                job.resume_token,
            ):
                job.execution_context = stored.execution_context
                job.resume_token = stored.resume_token
                cp.append_lifecycle_event(
                    job,
                    "idempotency_recovery",
                    {
                        "reason": (
                            "Resume token mismatch — "
                            "re-hydrated from checkpoint"
                        ),
                    },
                )

        return None


# ---------------------------------------------------------------------------
# Stage 3 — Degraded mode check
# ---------------------------------------------------------------------------


class DegradedModeStage(PipelineStage):
    """Evaluates whether the worker should enter degraded mode (v2).

    Degraded Mode is a restricted execution state entered when the runtime
    detects instability in S1, S2, or S3.  This stage:

    * Produces schema-compliant safe fallback output.
    * Emits escalation events (``worker_degraded``) on entry.
    * Checks recovery triggers on every cycle while degraded.
    * Emits recovery events (``worker_recovered``) on exit.

    The stage is stateful — it tracks ``_degraded`` per worker instance.
    While degraded, it short-circuits the pipeline with safe fallback output
    on every job until recovery signals are confirmed.
    """

    def __init__(self, degraded_mode: DegradedMode) -> None:
        self._degraded_mode = degraded_mode
        self._degraded: bool = False

    @property
    def name(self) -> str:
        return "degraded_mode"

    @property
    def is_degraded(self) -> bool:
        """``True`` if this worker is currently in degraded mode."""
        return self._degraded

    def evaluate(self, ctx: PipelineContext) -> Job | None:
        job = ctx.job
        cp = ctx.control_plane

        # ── Currently degraded → check recovery ────────────────────────
        if self._degraded:
            return self._handle_degraded_cycle(ctx)

        # ── Not degraded → evaluate thresholds and signals ─────────────
        degraded_ctx = DegradedContext(
            consecutive_failures=job.consecutive_failures,
            panic_count=job.panic_count,
            crash_count=job.crash_count,
            retry_exhausted=False,
            signal_state=ctx.signal_state,
            worker_id=self._degraded_mode.worker_id,
            job_id=job.job_id,
        )
        decision = self._degraded_mode.evaluate(degraded_ctx)

        if not decision.enter_degraded:
            return None

        # ── Enter degraded mode ────────────────────────────────────────
        self._enter_degraded(job, cp, decision)
        return job

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_degraded_cycle(self, ctx: PipelineContext) -> Job | None:
        """Handle a job while the worker is currently degraded.

        Checks recovery first.  If recovery is possible, emits the recovery
        event and continues the pipeline.  Otherwise produces fallback output.
        """
        job = ctx.job
        cp = ctx.control_plane

        degraded_ctx = DegradedContext(
            consecutive_failures=job.consecutive_failures,
            panic_count=job.panic_count,
            crash_count=job.crash_count,
            retry_exhausted=False,
            signal_state=ctx.signal_state,
            worker_id=self._degraded_mode.worker_id,
            job_id=job.job_id,
            already_degraded=True,
        )

        recovery_decision = self._degraded_mode.check_recovery(degraded_ctx)

        if (
            not recovery_decision.enter_degraded
            and recovery_decision.recovery_event is not None
        ):
            # ── Recovery confirmed ─────────────────────────────────────
            self._degraded = False
            cp.append_lifecycle_event(
                job,
                "worker_recovered",
                recovery_decision.recovery_event.to_dict(),
            )
            # Continue the pipeline — the job can now execute normally
            return None

        # ── Still degraded — produce fallback output ───────────────────
        fallback = SafeFallbackOutput(
            reason=recovery_decision.reason or "still_degraded",
            detail="Worker is in degraded mode and awaiting recovery signals.",
            job_id=job.job_id,
            fallback_action="short_circuit_and_acknowledge",
            recovery_hint="Worker is waiting for S1/S2/S3 stability signals.",
        )
        job.result = fallback.to_dict()
        cp.mark_succeeded(job, job.result)
        cp.save_checkpoint(job)
        log_job_finished(job)
        return job

    def _enter_degraded(
        self,
        job: Job,
        cp: Any,
        decision: DegradedDecision,
    ) -> None:
        """Enter degraded mode: store fallback output and emit escalation."""
        self._degraded = True

        # Schema-compliant fallback output
        if decision.fallback_output is not None:
            job.result = decision.fallback_output.to_dict()
        else:
            job.result = {
                "status": "degraded",
                "reason": decision.reason or "unknown",
                "detail": "Worker entered degraded mode.",
                "job_id": job.job_id,
                "fallback_action": "short_circuit_and_acknowledge",
                "recovery_hint": "Awaiting S1/S2/S3 stability signals.",
            }

        # Escalation event
        if decision.escalation_event is not None:
            cp.append_lifecycle_event(
                job,
                "worker_degraded",
                decision.escalation_event.to_dict(),
            )

        cp.mark_succeeded(job, job.result)
        cp.save_checkpoint(job)
        log_job_finished(job)



# ---------------------------------------------------------------------------
# Stage 4 — Multi-cycle execution loop
# ---------------------------------------------------------------------------


class ExecutionStage(PipelineStage):
    """Runs the multi-cycle cognitive execution loop.

    Each cycle:
    1. Wraps execution in ``PanicGuard`` for unexpected exceptions.
    2. Delegates to ``ToolRetryWrapper.execute()`` which handles retry
       logic and poison detection internally.
    3. Checks the return type — ``PanicDecision``, ``PoisonInstruction``,
       ``RetryInstruction``, or a normal result — and branches accordingly.
    4. Updates ``ExecutionContext``, cycles until ``done``.

    Returns the fully processed ``Job`` (succeeded, failed, or poisoned).
    """

    def __init__(
        self,
        retry_wrapper: ToolRetryWrapper,
        panic_guard: PanicGuard,
        timeout_seconds: int = 5,
    ) -> None:
        self._retry_wrapper = retry_wrapper
        self._panic_guard = panic_guard
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return "execution"

    def evaluate(self, ctx: PipelineContext) -> Job | None:
        job = ctx.job
        cp = ctx.control_plane

        # ---- Multi-cycle loop ----
        done = False
        attempt = 1
        while not done:
            cp.append_cycle_trace(job, "cycle_start", {})

            @self._panic_guard.wrap
            def run_cycle() -> Any:
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

            # Panic check
            if isinstance(output, PanicDecision) and output.is_panic:
                job.panic_count += 1
                job.consecutive_failures += 1
                cp.mark_failed(
                    job,
                    {
                        "error_type": output.safe_failure.error_type,
                        "message": output.safe_failure.message,
                    },
                )
                cp.save_checkpoint(job)
                log_job_finished(job)
                emit_metric("s4.repair.count", 1, {"repairtype": "panicrecovery"})
                return job

            # Poison check
            if isinstance(output, PoisonInstruction):
                job.failure_count += 1
                job.consecutive_failures += 1
                cp.mark_poison(job, output.reason)
                log_job_finished(job)
                emit_metric("s4.repair.count", 1, {"repairtype": "poisondetected"})
                return job

            # Retry instruction
            if isinstance(output, RetryInstruction):
                job.failure_count += 1
                job.consecutive_failures += 1
                time.sleep(output.delay_seconds)
                attempt = output.next_attempt
                cp.append_cycle_trace(
                    job,
                    "cycle_end",
                    {
                        "done": False,
                        "retry": True,
                        "delay": output.delay_seconds,
                        "attempt": attempt - 1,
                    },
                )
                cp.save_checkpoint(job)
                cp.issue_resume_token(job)
                continue

            # Successful cycle
            job.failure_count = 0
            job.consecutive_failures = 0

            if job.execution_context is not None:
                job.execution_context.cognitive_state = output.get(
                    "cognitive_state", {},
                )
                job.execution_context.memory = output.get("memory", {})
                job.execution_context.last_result = output.get("result")

            done = bool(output.get("done", False))
            attempt = 1

            cp.append_cycle_trace(job, "cycle_end", {"done": done})
            cp.save_checkpoint(job)
            cp.issue_resume_token(job)

        # ---- Loop complete ----
        cp.mark_succeeded(job, job.execution_context.last_result if job.execution_context else None)  # type: ignore[arg-type]
        cp.save_checkpoint(job)
        log_job_finished(job)
        return job
