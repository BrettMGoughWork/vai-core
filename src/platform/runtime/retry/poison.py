"""Pure deterministic poison job detection — no IO, no side effects.

A poison job has failed N consecutive times and must NOT be retried.
The detector returns a decision only; the caller (Worker) acts on it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PoisonDecision:
    """Returned by PoisonDetector.evaluate() — pure data, no logic."""

    is_poison: bool
    reason: str | None


@dataclass(frozen=True)
class PoisonContext:
    """Input to PoisonDetector.evaluate() — job metadata and error type."""

    job_id: str
    failure_count: int
    error_type: str


class PoisonDetector:
    """Deterministic poison detection. Pure logic — no IO, no state mutation.

    Args:
        max_failures: A job is declared poison when ``failure_count >= max_failures``.
    """

    def __init__(self, max_failures: int) -> None:
        self.max_failures = max_failures

    def evaluate(self, ctx: PoisonContext) -> PoisonDecision:
        """Return ``PoisonDecision(is_poison=True)`` if failures have been exhausted.

        Args:
            ctx: Context containing job metadata and the current error type.

        Returns:
            ``PoisonDecision(is_poison=True, reason=...)`` if
            ``failure_count >= max_failures``, otherwise
            ``PoisonDecision(is_poison=False, reason=None)``.
        """
        if ctx.failure_count >= self.max_failures:
            return PoisonDecision(
                is_poison=True,
                reason=f"Exceeded {self.max_failures} failures",
            )
        return PoisonDecision(is_poison=False, reason=None)


def default_poison_detector() -> PoisonDetector:
    """Create a ``PoisonDetector`` with the default threshold (5 failures)."""
    return PoisonDetector(max_failures=5)
