"""
Unit tests for recent VAI runtime changes.

Tests cover:
- RetryPolicy: Error type mapping to retry strategies
- LLMRetryWrapper: Automatic retry for LLM calls with timeout handling
- ToolRetryWrapper: Automatic retry for tool execution with idempotency enforcement
- CircuitBreaker: Failure tracking and cooldown-based circuit control
"""

import socket
import time
import pytest

from src.execution.retry.retry_policy import RetryPolicy, RetryStrategy
from src.execution.retry.circuit_breaker import CircuitBreaker


class TestRetryPolicy:
    """Tests for RetryPolicy error-to-strategy mapping."""

    def test_llm_error_strategy(self):
        """LLMError should be retryable with 2 max attempts and 0.2 backoff."""
        error = type("_", (), {})()
        error.__class__.__name__ = "LLMError"
        strategy = RetryPolicy.get(error)

        assert strategy.retryable is True
        assert strategy.max_attempts == 2
        assert strategy.backoff == 0.2
        assert strategy.idempotent_required is False

    def test_tool_error_strategy(self):
        """ToolError should be retryable with 1 attempt and idempotent requirement."""
        error = type("_", (), {})()
        error.__class__.__name__ = "ToolError"
        strategy = RetryPolicy.get(error)

        assert strategy.retryable is True
        assert strategy.max_attempts == 1
        assert strategy.backoff == 0.0
        assert strategy.idempotent_required is True

    def test_validation_error_strategy(self):
        """ValidationError should not be retryable."""
        error = type("_", (), {})()
        error.__class__.__name__ = "ValidationError"
        strategy = RetryPolicy.get(error)

        assert strategy.retryable is False
        assert strategy.max_attempts == 0
        assert strategy.backoff == 0.0
        assert strategy.idempotent_required is False

    def test_system_error_strategy(self):
        """SystemError should be retryable with 1 attempt."""
        error = type("_", (), {})()
        error.__class__.__name__ = "SystemError"
        strategy = RetryPolicy.get(error)

        assert strategy.retryable is True
        assert strategy.max_attempts == 1
        assert strategy.backoff == 0.0
        assert strategy.idempotent_required is False

    def test_unknown_error_type_raises(self):
        """Unknown error types should raise ValueError."""
        error = type("_", (), {})()
        error.__class__.__name__ = "UnknownError"
        
        with pytest.raises(ValueError, match="Unknown error type"):
            RetryPolicy.get(error)


class TestLLMRetryWrapper:
    """Tests for LLM retry wrapper with timeout handling."""

    def test_successful_call_no_retry(self):
        """Successful calls should not retry."""
        from src.execution.retry.llm_retry_wrapper import call_with_retry

        call_count = 0

        class MockLLMClient:
            def call(self, **kwargs):
                nonlocal call_count
                call_count += 1
                return {"response": "success"}

        client = MockLLMClient()
        result = call_with_retry(client, {"prompt": "test", "tools": [], "model": "test"})

        assert call_count == 1
        assert result == {"response": "success"}

    def test_timeout_retry_succeeds(self):
        """Timeout errors should retry and succeed."""
        from src.execution.retry.llm_retry_wrapper import call_with_retry

        call_count = 0

        class MockLLMClient:
            def call(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise socket.timeout("Timeout")
                return {"response": "success"}

        client = MockLLMClient()
        result = call_with_retry(client, {"prompt": "test", "tools": [], "model": "test"})

        assert call_count == 2
        assert result == {"response": "success"}

    def test_timeout_retry_exhausted(self):
        """Timeout errors should raise when retries exhausted."""
        from src.execution.retry.llm_retry_wrapper import call_with_retry

        call_count = 0

        class MockLLMClient:
            def call(self, **kwargs):
                nonlocal call_count
                call_count += 1
                raise socket.timeout("Timeout")

        client = MockLLMClient()

        with pytest.raises(socket.timeout):
            call_with_retry(client, {"prompt": "test", "tools": [], "model": "test"})

        # LLMError has max_attempts=2, so 1 initial + 2 retries = 3 total
        assert call_count == 3

    def test_system_error_not_retried(self):
        """Other exceptions treated as SystemError have limited retries."""
        from src.execution.retry.llm_retry_wrapper import call_with_retry

        call_count = 0

        class MockLLMClient:
            def call(self, **kwargs):
                nonlocal call_count
                call_count += 1
                raise RuntimeError("System error")

        client = MockLLMClient()

        with pytest.raises(RuntimeError):
            call_with_retry(client, {"prompt": "test", "tools": [], "model": "test"})

        # SystemError has max_attempts=1, so 1 initial + 1 retry = 2 total
        assert call_count == 2


class TestToolRetryWrapper:
    """Tests for tool retry wrapper with idempotency enforcement."""

    def test_successful_execution_no_retry(self):
        """Successful execution should not retry."""
        from src.execution.retry.tool_retry_wrapper import execute_with_retry

        class MockTool:
            is_idempotent = True
            call_count = 0

            def execute(self, args):
                self.call_count += 1
                return {"result": "success"}

        tool = MockTool()
        result = execute_with_retry(tool, {})

        assert tool.call_count == 1
        assert result == {"result": "success"}

    def test_tool_error_idempotent_retries(self):
        """Tool errors on idempotent tools should retry."""
        from src.execution.retry.tool_retry_wrapper import execute_with_retry

        class MockTool:
            is_idempotent = True
            call_count = 0

            def execute(self, args):
                self.call_count += 1
                if self.call_count == 1:
                    raise RuntimeError("Tool failed")
                return {"result": "success"}

        tool = MockTool()
        result = execute_with_retry(tool, {})

        assert tool.call_count == 2
        assert result == {"result": "success"}

    def test_tool_error_non_idempotent_no_retry(self):
        """Tool errors on non-idempotent tools should not retry."""
        from src.execution.retry.tool_retry_wrapper import execute_with_retry

        class MockTool:
            is_idempotent = False
            call_count = 0

            def execute(self, args):
                self.call_count += 1
                raise RuntimeError("Tool failed")

        tool = MockTool()

        with pytest.raises(RuntimeError):
            execute_with_retry(tool, {})

        assert tool.call_count == 1

    def test_system_error_retries(self):
        """System errors should retry."""
        from src.execution.retry.tool_retry_wrapper import execute_with_retry

        class MockTool:
            is_idempotent = True
            call_count = 0

            def execute(self, args):
                self.call_count += 1
                if self.call_count == 1:
                    raise Exception("System error")
                return {"result": "success"}

        tool = MockTool()
        result = execute_with_retry(tool, {})

        assert tool.call_count == 2
        assert result == {"result": "success"}


class TestCircuitBreaker:
    """Tests for circuit breaker failure tracking and cooldown."""

    def test_circuit_closed_initially(self):
        """Circuit should be closed (not open) initially."""
        cb = CircuitBreaker(failure_threshold=3)
        assert not cb.is_open("tool")

    def test_circuit_opens_at_threshold(self):
        """Circuit should open when failures reach threshold."""
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("tool")
        assert not cb.is_open("tool")

        cb.record_failure("tool")
        assert cb.is_open("tool")

    def test_success_closes_circuit(self):
        """Success should reset failures and close circuit."""
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure("tool")
        assert cb.is_open("tool")

        cb.record_success("tool")
        assert not cb.is_open("tool")
        assert cb.failures["tool"] == 0

    def test_cooldown_expiration(self):
        """Circuit should close after cooldown expires."""
        cb = CircuitBreaker(failure_threshold=1, cooldown=0.2)
        cb.record_failure("tool")
        assert cb.is_open("tool")

        time.sleep(0.3)
        assert not cb.is_open("tool")

    def test_multiple_tools_independent(self):
        """Different tools should have independent circuits."""
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("tool_a")
        cb.record_failure("tool_a")
        cb.record_failure("tool_b")

        assert cb.is_open("tool_a")
        assert not cb.is_open("tool_b")

    def test_failure_count_independent(self):
        """Failure counts should be independent per tool."""
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("tool_a")
        cb.record_failure("tool_b")
        cb.record_failure("tool_b")

        assert cb.failures["tool_a"] == 1
        assert cb.failures["tool_b"] == 2

    def test_open_method_explicitly_opens_circuit(self):
        """open() method should explicitly open circuit."""
        cb = CircuitBreaker(failure_threshold=10)
        assert not cb.is_open("tool")

        cb.open("tool")
        assert cb.is_open("tool")

    def test_explicit_open_respects_cooldown(self):
        """Explicitly opened circuit should respect cooldown."""
        cb = CircuitBreaker(cooldown=0.2)
        cb.open("tool")
        assert cb.is_open("tool")

        time.sleep(0.3)
        assert not cb.is_open("tool")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
