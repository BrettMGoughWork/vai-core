"""
LLM Retry Wrapper - Automatic retry logic for LLM calls.

Provides call_with_retry() function that wraps LLM calls with deterministic
retry logic based on RetryPolicy. Handles timeout and system errors with
automatic retries according to configured strategies.
"""

import socket
import time
from .retry_policy import RetryPolicy


def call_with_retry(llm_client, request):
    """
    Call LLM client with automatic retry logic.

    Wraps llm_client.call() with retry behavior based on RetryPolicy.
    Catches timeout and system errors, retries according to strategy,
    and re-raises when retries are exhausted or not allowed.

    Args:
        llm_client: LLMTransport instance with call() method
        request: dict with call parameters (prompt, tools, model, temperature, etc.)

    Returns:
        CoreLLMResponse from successful call

    Raises:
        socket.timeout: If timeout retries exhausted
        Exception: If other error retries exhausted or not retryable
    """

    # Dummy error classes for RetryPolicy lookup
    # These have __class__.__name__ that RetryPolicy.get() expects
    class _LLMErrorProxy:
        pass

    class _SystemErrorProxy:
        pass

    # Rename to match error type names expected by RetryPolicy
    _LLMErrorProxy.__name__ = "LLMError"
    _SystemErrorProxy.__name__ = "SystemError"

    last_error = None
    retry_count = 0

    while True:
        try:
            return llm_client.call(**request)
        except (socket.timeout, TimeoutError) as e:
            # Timeout errors treated as LLMError for retry policy
            last_error = e
            error_obj = _LLMErrorProxy()
        except Exception as e:
            # Other errors treated as SystemError for retry policy
            last_error = e
            error_obj = _SystemErrorProxy()

        # Consult retry policy for this error type
        strategy = RetryPolicy.get(error_obj)

        # Stop retrying if not allowed or retries exhausted
        # max_attempts is the maximum number of retry attempts
        if not strategy.retryable or retry_count >= strategy.max_attempts:
            raise last_error

        # Apply backoff before retry
        if strategy.backoff > 0:
            time.sleep(strategy.backoff)

        retry_count += 1
