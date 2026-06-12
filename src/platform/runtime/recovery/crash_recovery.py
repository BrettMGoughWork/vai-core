"""Crash Recovery v1 — Stratum-4 runtime.

Pure, deterministic crash recovery evaluation.  Answers the question "should
this job be recovered?" based on job state and checkpoint availability.

Recovery does NOT:
  - mutate job state
  - write to persistence
  - push to queue or DLQ
  - sleep or wait
  - log or trace

Idempotency rule: a cycle may only advance when the provided resume token
matches the stored resume token.  A mismatch means a crash occurred between
the previous checkpoint and the current execution attempt — the worker must
restart from the last checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.platform.runtime.execution_context import ExecutionContext


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecoveryDecision:
    """Result of a crash recovery evaluation.

    Attributes:
        should_recover: ``True`` when the job should be recovered.
        resume_token:   The resume token to use for recovery (if any).
        reason:         Human-readable explanation of the decision.
    """

    should_recover: bool
    resume_token: str | None
    reason: str | None


@dataclass(frozen=True)
class RecoveryInstruction:
    """Instruction for the worker to recover from a crash.

    Attributes:
        resume_token: The token to use when resuming execution.
        reason:       Why recovery was triggered.
    """

    resume_token: str | None
    reason: str


@dataclass(frozen=True)
class RecoveryContext:
    """Input context for crash recovery evaluation.

    Attributes:
        job_id:             The job's unique identifier.
        last_checkpoint:    The last persisted ``ExecutionContext``, or
                            ``None`` if the job has never been checkpointed.
        last_resume_token:  The last persisted resume token, or ``None``.
        job_state:          The job's current lifecycle state as a string
                            (e.g. ``"pending"``, ``"running"``).
    """

    job_id: str
    last_checkpoint: ExecutionContext | None
    last_resume_token: str | None
    job_state: str


# ---------------------------------------------------------------------------
# Crash recovery evaluator
# ---------------------------------------------------------------------------


class CrashRecovery:
    """Pure deterministic crash recovery evaluator.

    Usage::

        recovery = CrashRecovery()
        decision = recovery.evaluate(RecoveryContext(...))
        if decision.should_recover:
            # worker restarts from checkpoint
    """

    @staticmethod
    def evaluate(ctx: RecoveryContext) -> RecoveryDecision:
        """Evaluate whether the job should be recovered.

        Pure deterministic logic:

        1. No checkpoint → cannot recover.
        2. Job state is not ``"running"`` → no crash to recover from.
        3. Checkpoint exists and state is ``"running"`` → crash detected,
           recover using the last resume token.

        Args:
            ctx: The recovery context.

        Returns:
            A ``RecoveryDecision`` with the evaluation result.
        """
        # 1. No checkpoint → cannot recover
        if ctx.last_checkpoint is None:
            return RecoveryDecision(
                should_recover=False,
                resume_token=None,
                reason="No checkpoint found",
            )

        # 2. Not in running state → no crash to recover from
        if ctx.job_state != "running":
            return RecoveryDecision(
                should_recover=False,
                resume_token=None,
                reason=f"Job state is '{ctx.job_state}', not 'running'",
            )

        # 3. Checkpoint exists + state is running → crash detected
        return RecoveryDecision(
            should_recover=True,
            resume_token=ctx.last_resume_token,
            reason="Crash detected: job left in RUNNING state with checkpoint",
        )

    @staticmethod
    def validate_resume_token(
        expected: str | None, actual: str | None,
    ) -> bool:
        """Idempotency: a cycle may only advance when tokens match.

        If there is no expected token (first cycle), any token is valid.

        Args:
            expected: The resume token stored in the job's checkpoint.
            actual:   The resume token provided for the current execution.

        Returns:
            ``True`` if the tokens match (safe to advance).
        """
        if expected is None:
            return True
        return expected == actual


def default_crash_recovery() -> CrashRecovery:
    """Factory: return a ``CrashRecovery`` instance with default settings."""
    return CrashRecovery()
