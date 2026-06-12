"""Tool retry wrapper — catches errors, evaluates retry policy, returns instructions.

The wrapper does NOT sleep or retry. It returns RetryInstruction for the caller
(typically the Worker) to act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.platform.runtime.retry.poison import (
    PoisonContext,
    PoisonDetector,
    default_poison_detector,
)
from src.platform.runtime.retry.policy import (
    PlatformRetryPolicy,
    RetryContext,
    default_retry_policy,
)


@dataclass(frozen=True)
class RetryInstruction:
    """Instructs the caller to retry after delay_seconds with next_attempt."""

    delay_seconds: float
    next_attempt: int


@dataclass(frozen=True)
class PoisonInstruction:
    """Instructs the caller that the job is poison and must NOT be retried."""

    is_poison: bool
    reason: str


class ToolRetryWrapper:
    """Wraps a callable with poison detection and retry policy evaluation.

    Evaluation order:
        1. Catch exception.
        2. **Poison check** — if the job has failed too many times, return
           ``PoisonInstruction`` (no exception raised).
        3. **Retry check** — if the error type is retryable and attempts
           remain, return ``RetryInstruction``.
        4. Otherwise **re-raise** the original exception.

    The wrapper does NOT sleep, mutate state, or interact with the job store.
    """

    def __init__(
        self,
        fn: Callable,
        retry_policy: PlatformRetryPolicy | None = None,
        poison_detector: PoisonDetector | None = None,
    ):
        self.fn = fn
        self.retry_policy = retry_policy or default_retry_policy()
        self._poison_detector = poison_detector

    def execute(
        self,
        *args: Any,
        attempt: int = 1,
        job_id: str | None = None,
        failure_count: int = 0,
        **kwargs: Any,
    ) -> Any:
        try:
            return self.fn(*args, **kwargs)
        except Exception as e:
            # --- Poison check (before retry evaluation) -------------------
            if self._poison_detector is not None and job_id is not None:
                poison_ctx = PoisonContext(
                    job_id=job_id,
                    failure_count=failure_count,
                    error_type=e.__class__.__name__,
                )
                poison_decision = self._poison_detector.evaluate(poison_ctx)
                if poison_decision.is_poison:
                    return PoisonInstruction(
                        is_poison=True,
                        reason=poison_decision.reason,
                    )

            # --- Retry evaluation -----------------------------------------
            ctx = RetryContext(
                attempt=attempt,
                error_type=e.__class__.__name__,
            )
            decision = self.retry_policy.evaluate(ctx)
            if not decision.should_retry:
                raise
            return RetryInstruction(
                delay_seconds=decision.delay_seconds,
                next_attempt=attempt + 1,
            )
