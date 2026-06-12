"""Degraded Mode v2 — Stratum-4 Safety Kernel.

Architecture
============
Degraded Mode is a restricted execution state entered when the runtime detects
instability in:

* **S1** (CoreStep pipeline)
* **S2** (Job lifecycle / persistence)
* **S3** (Orchestration / scheduling)

In Degraded Mode the worker must:

- stop all non-essential behaviour
- disable all heavy or unsafe capabilities
- short-circuit complex logic
- produce safe fallback output
- avoid cascading failures
- avoid retries
- avoid tool calls
- avoid multi-step reasoning

This module implements the full Degraded Mode semantics — evaluation, safe
fallback schema, escalation events, recovery triggers, and behavioural
contract enforcement.

All logic is pure and deterministic — no IO, no side-effects, no backend
dependencies.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Safe Fallback Output — REQUIRED SCHEMA
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SafeFallbackOutput:
    """Schema-mandated safe fallback output for degraded mode responses.

    When in Degraded Mode, all worker responses must conform to this schema.
    No hallucination, no multi-step reasoning, no tool calls, no retries.
    """

    status: str = "degraded"
    reason: str = ""
    detail: str = ""
    job_id: str = ""
    fallback_action: str = ""
    recovery_hint: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return as a plain dict for serialisation."""
        return {
            "status": self.status,
            "reason": self.reason,
            "detail": self.detail,
            "job_id": self.job_id,
            "fallback_action": self.fallback_action,
            "recovery_hint": self.recovery_hint,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> SafeFallbackOutput:
        """Reconstruct from a plain dict (e.g. deserialised from job store)."""
        return SafeFallbackOutput(
            status=str(d.get("status", "degraded")),
            reason=str(d.get("reason", "")),
            detail=str(d.get("detail", "")),
            job_id=str(d.get("job_id", "")),
            fallback_action=str(d.get("fallback_action", "")),
            recovery_hint=str(d.get("recovery_hint", "")),
        )


# ---------------------------------------------------------------------------
# Escalation Event — REQUIRED SCHEMA
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerDegradedEvent:
    """Escalation event emitted when entering degraded mode.

    Sent to:
        * S4 Supervisor
        * S3 Scheduler
        * S2 Job Manager

    Must not be sent to the LLM or external systems.
    """

    event: str = "worker_degraded"
    worker_id: str = ""
    job_id: str = ""
    severity: str = "high"
    timestamp: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return as a plain dict for serialisation."""
        return {
            "event": self.event,
            "worker_id": self.worker_id,
            "job_id": self.job_id,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class WorkerRecoveredEvent:
    """Event emitted when the worker exits degraded mode.

    A worker may exit Degraded Mode only when all recovery triggers
    are satisfied (see :meth:`DegradedMode.check_recovery`).
    """

    event: str = "worker_recovered"
    worker_id: str = ""
    timestamp: str = ""
    stability_window: int = 0  # N consecutive stable cycles

    def to_dict(self) -> dict[str, Any]:
        """Return as a plain dict for serialisation."""
        return {
            "event": self.event,
            "worker_id": self.worker_id,
            "timestamp": self.timestamp,
            "stability_window": self.stability_window,
        }


# ---------------------------------------------------------------------------
# Signal State — from S1, S2, S3
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalState:
    """Aggregated stability signals from S1, S2, and S3 strata.

    Used by :meth:`DegradedMode.evaluate` and :meth:`DegradedMode.check_recovery`
    to determine whether to enter or exit Degraded Mode.
    """

    s1_stable: bool = True
    """``True`` if S1 (CoreStep pipeline) reports stable execution."""

    s1_stable_cycles: int = 0
    """Consecutive stable S1 cycles — used for recovery gate."""

    s2_stable: bool = True
    """``True`` if S2 (job lifecycle / persistence) reports envelope integrity."""

    s3_stable: bool = True
    """``True`` if S3 (orchestration / scheduling) reports heartbeat stability."""

    new_critical_errors: int = 0
    """Number of new critical errors in the last M seconds (recovery gate)."""

    last_error_timestamp: float = 0.0
    """Unix timestamp of the most recent critical error (for M-second gate)."""


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DegradedDecision:
    """Result of evaluating whether the system should enter degraded mode."""

    enter_degraded: bool
    reason: str | None = None
    fallback_output: SafeFallbackOutput | None = None
    escalation_event: WorkerDegradedEvent | None = None
    recovery_event: WorkerRecoveredEvent | None = None
    currently_degraded: bool = False
    """``True`` if the worker is already in degraded mode entering this eval."""


@dataclass(frozen=True)
class DegradedContext:
    """Signals and context collected from the current job cycle.

    Attributes:
        consecutive_failures: Number of consecutive execution failures.
        panic_count:          Number of panics encountered.
        crash_count:          Number of crashes encountered.
        retry_exhausted:      ``True`` if the retry policy has been exhausted.
        signal_state:         Optional aggregated S1/S2/S3 stability signals.
        worker_id:            Identifier of the worker being evaluated.
        job_id:               Identifier of the current job.
        already_degraded:     ``True`` if the worker is already in degraded mode.
    """

    consecutive_failures: int = 0
    panic_count: int = 0
    crash_count: int = 0
    retry_exhausted: bool = False
    signal_state: SignalState | None = None
    worker_id: str = ""
    job_id: str = ""
    already_degraded: bool = False


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

DEFAULT_DEGRADED_THRESHOLDS: dict[str, int] = {
    "failures": 3,
    "panics": 1,
    "crashes": 1,
}

DEFAULT_RECOVERY_STABLE_CYCLES: int = 5
"""N: number of consecutive stable cycles required before recovery."""

DEFAULT_RECOVERY_ERROR_WINDOW_SECONDS: float = 60.0
"""M: seconds without new critical errors required before recovery."""


# ---------------------------------------------------------------------------
# Pure evaluator logic
# ---------------------------------------------------------------------------

# Machine-readable reason keys — used in SafeFallbackOutput.reason
REASON_CONSECUTIVE_FAILURES = "consecutive_failures_exceeded"
REASON_PANIC_THRESHOLD = "panic_threshold_exceeded"
REASON_CRASH_THRESHOLD = "crash_threshold_exceeded"
REASON_RETRY_EXHAUSTED = "retry_policy_exhausted"
REASON_S1_INSTABILITY = "s1_corestep_instability"
REASON_S2_INSTABILITY = "s2_job_persistence_instability"
REASON_S3_INSTABILITY = "s3_scheduler_instability"
REASON_MULTI_SIGNAL = "multiple_strata_instability"


class DegradedMode:
    """Deterministic pure-logic degraded-mode evaluator.

    Args:
        thresholds: Dict with keys ``failures``, ``panics``, ``crashes``.
        recovery_stable_cycles: Consecutive stable S1 cycles needed for recovery.
        recovery_error_window_seconds: Seconds without critical errors for recovery.
        worker_id: Identifier of this worker (used in escalation events).
    """

    def __init__(
        self,
        thresholds: dict[str, int] | None = None,
        recovery_stable_cycles: int = DEFAULT_RECOVERY_STABLE_CYCLES,
        recovery_error_window_seconds: float = DEFAULT_RECOVERY_ERROR_WINDOW_SECONDS,
        worker_id: str = "",
    ) -> None:
        self.thresholds = thresholds or dict(DEFAULT_DEGRADED_THRESHOLDS)
        self.recovery_stable_cycles = recovery_stable_cycles
        self.recovery_error_window_seconds = recovery_error_window_seconds
        self.worker_id = worker_id

    # ------------------------------------------------------------------
    # Entry evaluation
    # ------------------------------------------------------------------

    def evaluate(self, ctx: DegradedContext) -> DegradedDecision:
        """Evaluate whether to enter degraded mode.

        Decision order (first match wins):

        1. Retry policy exhausted
        2. Consecutive failures exceed threshold
        3. Panic count exceeds threshold
        4. Crash count exceeds threshold
        5. S1/S2/S3 signal instability (if signal_state provided)

        Returns:
            A :class:`DegradedDecision` with fallback output and escalation
            event if entering degraded mode.
        """
        # ── If already degraded, stay degraded — no re-evaluation needed ──
        if ctx.already_degraded:
            return DegradedDecision(
                enter_degraded=True,
                reason="already_degraded",
                currently_degraded=True,
            )

        reason: str | None = None

        if ctx.retry_exhausted:
            reason = REASON_RETRY_EXHAUSTED
        elif ctx.consecutive_failures >= self.thresholds.get("failures", 3):
            reason = REASON_CONSECUTIVE_FAILURES
        elif ctx.panic_count >= self.thresholds.get("panics", 1):
            reason = REASON_PANIC_THRESHOLD
        elif ctx.crash_count >= self.thresholds.get("crashes", 1):
            reason = REASON_CRASH_THRESHOLD
        elif ctx.signal_state is not None:
            reason = self._check_signal_instability(ctx.signal_state)

        if reason is None:
            return DegradedDecision(enter_degraded=False, reason=None)

        # Build schema-compliant fallback output
        detail = self._build_detail(reason, ctx)
        fallback_action = "short_circuit_and_acknowledge"
        recovery_hint = self._build_recovery_hint(reason)

        fallback = SafeFallbackOutput(
            reason=reason,
            detail=detail,
            job_id=ctx.job_id,
            fallback_action=fallback_action,
            recovery_hint=recovery_hint,
        )

        # Build escalation event
        escalation = WorkerDegradedEvent(
            worker_id=self.worker_id or ctx.worker_id,
            job_id=ctx.job_id,
            timestamp=_iso_timestamp(),
            reason=reason,
        )

        return DegradedDecision(
            enter_degraded=True,
            reason=reason,
            fallback_output=fallback,
            escalation_event=escalation,
        )

    # ------------------------------------------------------------------
    # Recovery check
    # ------------------------------------------------------------------

    def check_recovery(self, ctx: DegradedContext) -> DegradedDecision:
        """Check whether the worker may exit degraded mode.

        Recovery requires **all** of the following:

        1. ``S1`` reports stable CoreStep execution for N consecutive cycles
           (``recovery_stable_cycles``).
        2. ``S2`` reports job persistence and envelope integrity.
        3. ``S3`` reports scheduler heartbeat stability.
        4. No new critical errors have occurred in the last M seconds
           (``recovery_error_window_seconds``).

        Args:
            ctx: Current degraded context with signal_state.

        Returns:
            A :class:`DegradedDecision` with ``enter_degraded=False`` and
            a :class:`WorkerRecoveredEvent` if recovery is possible.
        """
        if not ctx.already_degraded:
            return DegradedDecision(enter_degraded=False, reason=None)

        sig = ctx.signal_state
        if sig is None:
            # No signal data — cannot verify recovery; stay degraded
            return DegradedDecision(
                enter_degraded=True,
                reason="insufficient_signals",
                currently_degraded=True,
            )

        # Gate 1: S1 stable for N cycles
        if not sig.s1_stable or sig.s1_stable_cycles < self.recovery_stable_cycles:
            return DegradedDecision(
                enter_degraded=True,
                reason="s1_not_stable",
                currently_degraded=True,
            )

        # Gate 2: S2 envelope integrity
        if not sig.s2_stable:
            return DegradedDecision(
                enter_degraded=True,
                reason="s2_not_stable",
                currently_degraded=True,
            )

        # Gate 3: S3 heartbeat
        if not sig.s3_stable:
            return DegradedDecision(
                enter_degraded=True,
                reason="s3_not_stable",
                currently_degraded=True,
            )

        # Gate 4: No critical errors in window
        if sig.new_critical_errors > 0:
            return DegradedDecision(
                enter_degraded=True,
                reason="critical_errors_in_window",
                currently_degraded=True,
            )

        now = time.time()
        window_sec = self.recovery_error_window_seconds
        if sig.last_error_timestamp > 0 and (now - sig.last_error_timestamp) < window_sec:
            return DegradedDecision(
                enter_degraded=True,
                reason="recent_critical_error",
                currently_degraded=True,
            )

        # All gates passed — recovery
        recovery_event = WorkerRecoveredEvent(
            worker_id=self.worker_id or ctx.worker_id,
            timestamp=_iso_timestamp(),
            stability_window=self.recovery_stable_cycles,
        )

        return DegradedDecision(
            enter_degraded=False,
            reason=None,
            recovery_event=recovery_event,
        )

    # ------------------------------------------------------------------
    # Behavioural contract enforcement
    # ------------------------------------------------------------------

    # Forbidden operations while degraded — machine-readable labels
    FORBIDDEN_OPS: frozenset[str] = frozenset({
        "retry",
        "backoff",
        "tool_call",
        "multi_step_reasoning",
        "agentic_behaviour",
        "external_api_call",
        "state_mutation",
        "job_completion_attempt",
    })

    # Allowed operations while degraded
    ALLOWED_OPS: frozenset[str] = frozenset({
        "produce_fallback_output",
        "emit_escalation_event",
        "wait_for_recovery_signals",
        "maintain_heartbeat",
        "maintain_isolation",
    })

    @classmethod
    def is_op_allowed(cls, operation: str) -> bool:
        """Check whether *operation* is permitted while degraded.

        Args:
            operation: Machine-readable operation label.

        Returns:
            ``True`` if the operation is in the allowed set.
        """
        return operation in cls.ALLOWED_OPS

    @classmethod
    def is_op_forbidden(cls, operation: str) -> bool:
        """Check whether *operation* is forbidden while degraded.

        Args:
            operation: Machine-readable operation label.

        Returns:
            ``True`` if the operation is in the forbidden set.
        """
        return operation in cls.FORBIDDEN_OPS

    @classmethod
    def validate_behaviour(cls, operations: list[str]) -> list[str]:
        """Validate a list of intended operations against the contract.

        Args:
            operations: List of machine-readable operation labels.

        Returns:
            List of forbidden operation labels (empty if all are ok).
        """
        return [op for op in operations if cls.is_op_forbidden(op)]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_signal_instability(self, sig: SignalState) -> str | None:
        """Check S1/S2/S3 signal state for instability.

        Returns a machine-readable reason key, or ``None`` if all stable.
        """
        unstable: list[str] = []
        if not sig.s1_stable:
            unstable.append("S1")
        if not sig.s2_stable:
            unstable.append("S2")
        if not sig.s3_stable:
            unstable.append("S3")

        if not unstable:
            return None
        if len(unstable) >= 2:
            return REASON_MULTI_SIGNAL
        if unstable[0] == "S1":
            return REASON_S1_INSTABILITY
        if unstable[0] == "S2":
            return REASON_S2_INSTABILITY
        return REASON_S3_INSTABILITY

    def _build_detail(self, reason: str, ctx: DegradedContext) -> str:
        """Build a human-readable detail string for the fallback output."""
        details: dict[str, str] = {
            REASON_CONSECUTIVE_FAILURES: (
                f"Worker entered degraded mode after "
                f"{ctx.consecutive_failures} consecutive execution failures."
            ),
            REASON_PANIC_THRESHOLD: (
                f"Worker entered degraded mode after "
                f"{ctx.panic_count} panics."
            ),
            REASON_CRASH_THRESHOLD: (
                f"Worker entered degraded mode after "
                f"{ctx.crash_count} crashes."
            ),
            REASON_RETRY_EXHAUSTED: (
                "Worker entered degraded mode because the retry policy "
                "has been exhausted."
            ),
            REASON_S1_INSTABILITY: (
                "Worker entered degraded mode because S1 (CoreStep pipeline) "
                "reported instability."
            ),
            REASON_S2_INSTABILITY: (
                "Worker entered degraded mode because S2 (job lifecycle) "
                "reported persistence or envelope integrity issues."
            ),
            REASON_S3_INSTABILITY: (
                "Worker entered degraded mode because S3 (orchestration) "
                "reported scheduler heartbeat instability."
            ),
            REASON_MULTI_SIGNAL: (
                "Worker entered degraded mode because multiple strata "
                "(S1, S2, S3) reported instability."
            ),
        }
        return details.get(reason, f"Degraded mode activated: {reason}")

    def _build_recovery_hint(self, reason: str) -> str:
        """Build a recovery hint string for the fallback output."""
        hints: dict[str, str] = {
            REASON_CONSECUTIVE_FAILURES: (
                f"Recovery requires {self.recovery_stable_cycles} consecutive "
                f"stable S1 cycles and no critical errors for "
                f"{self.recovery_error_window_seconds}s."
            ),
            REASON_PANIC_THRESHOLD: (
                f"Recovery requires {self.recovery_stable_cycles} consecutive "
                f"stable S1 cycles and no critical errors for "
                f"{self.recovery_error_window_seconds}s."
            ),
            REASON_CRASH_THRESHOLD: (
                f"Recovery requires {self.recovery_stable_cycles} consecutive "
                f"stable S1 cycles and no critical errors for "
                f"{self.recovery_error_window_seconds}s."
            ),
            REASON_RETRY_EXHAUSTED: (
                f"Recovery requires {self.recovery_stable_cycles} consecutive "
                f"stable S1 cycles and no critical errors for "
                f"{self.recovery_error_window_seconds}s."
            ),
            REASON_S1_INSTABILITY: (
                "Recovery requires S1 to report stable CoreStep execution for "
                f"{self.recovery_stable_cycles} consecutive cycles."
            ),
            REASON_S2_INSTABILITY: (
                "Recovery requires S2 to report job persistence and envelope "
                "integrity."
            ),
            REASON_S3_INSTABILITY: (
                "Recovery requires S3 to report scheduler heartbeat stability."
            ),
            REASON_MULTI_SIGNAL: (
                "Recovery requires all strata (S1, S2, S3) to report stability."
            ),
        }
        return hints.get(
            reason,
            "Recovery requires all stability signals to be green.",
        )


def default_degraded_mode(worker_id: str = "") -> DegradedMode:
    """Factory that returns a ``DegradedMode`` with default thresholds.

    Args:
        worker_id: Optional identifier for this worker instance.

    Returns:
        A ``DegradedMode`` with default configuration.
    """
    return DegradedMode(
        thresholds=dict(DEFAULT_DEGRADED_THRESHOLDS),
        recovery_stable_cycles=DEFAULT_RECOVERY_STABLE_CYCLES,
        recovery_error_window_seconds=DEFAULT_RECOVERY_ERROR_WINDOW_SECONDS,
        worker_id=worker_id,
    )


def _iso_timestamp() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
