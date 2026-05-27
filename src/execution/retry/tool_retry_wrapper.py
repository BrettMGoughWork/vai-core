"""
Tool Retry Wrapper - Automatic retry logic for tool execution.

Provides execute_with_retry() function that wraps tool execution with deterministic
retry logic based on RetryPolicy. Respects tool idempotency constraints and retries
according to configured strategies.
"""

import time
from .retry_policy import RetryPolicy


def execute_with_retry(tool, args):
    """
    Execute a tool with automatic retry logic.

    Wraps tool.run(**args) with retry behavior based on RetryPolicy.
    Catches tool execution errors, respects tool idempotency constraints,
    and retries according to strategy. Re-raises when retries are exhausted
    or not allowed.

    Args:
        tool: Tool instance with run(**kwargs) method and is_idempotent attribute
        args: Arguments dict to pass to tool.run(**args)

    Returns:
        Result from successful tool.run(**args) call

    Raises:
        Exception: If tool operation fails and retries exhausted or not allowed
    """

    # Proxy error classes for RetryPolicy lookup
    # Maps caught exceptions to error types expected by RetryPolicy
    class _ToolErrorProxy:
        pass

    class _SystemErrorProxy:
        pass

    # Rename to match error type names expected by RetryPolicy
    _ToolErrorProxy.__name__ = "ToolError"
    _SystemErrorProxy.__name__ = "SystemError"

    last_error = None
    retry_count = 0

    while True:
        try:
            return tool.run(**args)
        except Exception as e:
            # Classify caught exception as ToolError or SystemError
            # ToolError for tool-specific failures, SystemError for other failures
            last_error = e
            if "Tool" in type(e).__name__ or "tool" in str(e).lower():
                error_obj = _ToolErrorProxy()
            else:
                error_obj = _SystemErrorProxy()

        # Consult retry policy for this error type
        strategy = RetryPolicy.get(error_obj)

        # Stop retrying if:
        # 1. Error not retryable, or
        # 2. Retries exhausted, or
        # 3. Idempotency required but tool not idempotent
        if (
            not strategy.retryable
            or retry_count >= strategy.max_attempts
            or (strategy.idempotent_required and not tool.is_idempotent)
        ):
            raise last_error

        # Apply backoff before retry
        if strategy.backoff > 0:
            time.sleep(strategy.backoff)

        retry_count += 1
