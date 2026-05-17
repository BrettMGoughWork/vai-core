"""
Retry Policy Module - Deterministic retry strategy mapping for error types.

This module defines retry strategies for different error types encountered
during execution. Each error type maps to a RetryStrategy that determines
whether the operation should be retried, how many times, and with what backoff.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class RetryStrategy:
    """
    Retry strategy configuration for a given error type.

    Attributes:
        retryable: Whether the error allows for retry attempts
        max_attempts: Maximum number of retry attempts (1+ if retryable)
        backoff: Backoff multiplier for exponential backoff between retries
        idempotent_required: Whether the operation must be idempotent to retry
    """

    retryable: bool
    max_attempts: int
    backoff: float
    idempotent_required: bool


class RetryPolicy:
    """
    Deterministic mapping from error types to RetryStrategy instances.

    This class provides a pure mapping function that returns the appropriate
    retry strategy for each error type. No side effects or state mutation.
    """

    @staticmethod
    def get(error: Any) -> RetryStrategy:
        """
        Get the retry strategy for a given error.

        Maps error type (as determined by error.__class__.__name__)
        to the appropriate RetryStrategy.

        Args:
            error: An error instance to determine the retry strategy for

        Returns:
            RetryStrategy: The appropriate retry strategy for this error type

        Raises:
            ValueError: If the error type is not recognized
        """
        error_type = error.__class__.__name__

        if error_type == "LLMError":
            return RetryStrategy(
                retryable=True,
                max_attempts=2,
                backoff=0.2,
                idempotent_required=False,
            )

        elif error_type == "ToolError":
            return RetryStrategy(
                retryable=True,
                max_attempts=1,
                backoff=0.0,
                idempotent_required=True,
            )

        elif error_type == "ValidationError":
            return RetryStrategy(
                retryable=False,
                max_attempts=0,
                backoff=0.0,
                idempotent_required=False,
            )

        elif error_type == "SystemError":
            return RetryStrategy(
                retryable=True,
                max_attempts=1,
                backoff=0.0,
                idempotent_required=False,
            )

        else:
            raise ValueError(f"Unknown error type: {error_type}")
