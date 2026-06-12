"""Pure deterministic retry policy evaluation — no IO, no side effects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryDecision:
    """Returned by RetryPolicy.evaluate() — pure data, no logic."""

    should_retry: bool
    delay_seconds: float | None


@dataclass(frozen=True)
class RetryContext:
    """Input to RetryPolicy.evaluate() — current attempt and error type."""

    attempt: int
    error_type: str


DEFAULT_RETRY_RULES: dict[str, dict] = {
    "TransientNetworkError": {
        "max_attempts": 3,
        "base_delay": 1.0,
    },
    "RateLimitError": {
        "max_attempts": 5,
        "base_delay": 2.0,
    },
    "TimeoutError": {
        "max_attempts": 2,
        "base_delay": 1.5,
    },
}


class RetryPolicy:
    """Deterministic retry policy. Pure logic — no IO, no sleeping."""

    def __init__(self, rules: dict[str, dict]):
        self.rules = rules

    def evaluate(self, ctx: RetryContext) -> RetryDecision:
        rule = self.rules.get(ctx.error_type)
        if rule is None:
            return RetryDecision(should_retry=False, delay_seconds=None)

        max_attempts = rule["max_attempts"]
        if ctx.attempt >= max_attempts:
            return RetryDecision(should_retry=False, delay_seconds=None)

        base_delay = rule["base_delay"]
        delay = base_delay * (2 ** (ctx.attempt - 1))
        return RetryDecision(should_retry=True, delay_seconds=delay)


def default_retry_policy() -> RetryPolicy:
    return RetryPolicy(DEFAULT_RETRY_RULES)
