"""Tool retry wrapper — catches errors, evaluates retry policy, returns instructions.

The wrapper does NOT sleep or retry. It returns RetryInstruction for the caller
(typically the Worker) to act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.platform.runtime.retry.policy import (
    RetryContext,
    RetryPolicy,
    default_retry_policy,
)


@dataclass(frozen=True)
class RetryInstruction:
    """Instructs the caller to retry after delay_seconds with next_attempt."""

    delay_seconds: float
    next_attempt: int


class ToolRetryWrapper:
    """Wraps a callable with retry policy evaluation.

    - On success: returns the callable's result.
    - On failure with retry eligible: returns RetryInstruction.
    - On failure without retry eligible: re-raises the original exception.
    """

    def __init__(self, fn: Callable, retry_policy: RetryPolicy | None = None):
        self.fn = fn
        self.retry_policy = retry_policy or default_retry_policy()

    def execute(self, *args: Any, attempt: int = 1, **kwargs: Any) -> Any:
        try:
            return self.fn(*args, **kwargs)
        except Exception as e:
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
