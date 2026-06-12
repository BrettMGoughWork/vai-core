"""Degraded Mode v1 — Stratum-4 safety subsystem.

If Stratum-1 or Stratum-2 become unstable, unresponsive, or repeatedly fail,
the worker must fall back to a simpler, safe execution path.  Degraded Mode
is pure logic only — no IO, no side-effects, no backend dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DegradedDecision:
    """Result of evaluating whether the system should enter degraded mode."""

    enter_degraded: bool
    reason: str | None


@dataclass(frozen=True)
class DegradedContext:
    """Signals collected from the current job cycle."""

    consecutive_failures: int
    panic_count: int
    crash_count: int
    retry_exhausted: bool


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------


DEFAULT_DEGRADED_THRESHOLDS: dict[str, int] = {
    "failures": 3,
    "panics": 1,
    "crashes": 1,
}


class DegradedMode:
    """Deterministic pure-logic degraded-mode evaluator.

    Args:
        thresholds: Dict with keys ``failures``, ``panics``, ``crashes``.
    """

    def __init__(self, thresholds: dict[str, int]) -> None:
        self.thresholds = thresholds

    def evaluate(self, ctx: DegradedContext) -> DegradedDecision:
        """Evaluate whether to enter degraded mode.

        Returns ``enter_degraded=True`` if *any* threshold is exceeded.
        """
        if ctx.retry_exhausted:
            return DegradedDecision(
                enter_degraded=True,
                reason="Retry policy exhausted",
            )
        if ctx.consecutive_failures >= self.thresholds.get("failures", 3):
            return DegradedDecision(
                enter_degraded=True,
                reason=f"Consecutive failures ({ctx.consecutive_failures}) "
                       f"exceeds threshold ({self.thresholds.get('failures', 3)})",
            )
        if ctx.panic_count >= self.thresholds.get("panics", 1):
            return DegradedDecision(
                enter_degraded=True,
                reason=f"Panic count ({ctx.panic_count}) "
                       f"exceeds threshold ({self.thresholds.get('panics', 1)})",
            )
        if ctx.crash_count >= self.thresholds.get("crashes", 1):
            return DegradedDecision(
                enter_degraded=True,
                reason=f"Crash count ({ctx.crash_count}) "
                       f"exceeds threshold ({self.thresholds.get('crashes', 1)})",
            )
        return DegradedDecision(enter_degraded=False, reason=None)


def default_degraded_mode() -> DegradedMode:
    """Factory that returns a ``DegradedMode`` with default thresholds."""
    return DegradedMode(DEFAULT_DEGRADED_THRESHOLDS)
