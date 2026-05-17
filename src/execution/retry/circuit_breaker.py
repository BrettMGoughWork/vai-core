"""
Circuit Breaker Pattern - Prevent cascading failures in tool execution.

Implements a circuit breaker to track tool failures and prevent execution
when a tool has exceeded its failure threshold. Uses a cooldown period before
allowing recovery attempts.
"""

import time


class CircuitBreaker:
    """
    Simple circuit breaker for tool execution.

    Tracks failures per tool and prevents execution when failure threshold
    is exceeded. Implements cooldown period for recovery attempts.

    A tool is "open" (blocked) when:
    1. Failures for that tool >= failure_threshold, AND
    2. Current time < open_until[tool_name]

    The circuit transitions from open to closed when the cooldown period expires.
    """

    def __init__(self, failure_threshold: int = 3, cooldown: float = 5.0):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit (default 3)
            cooldown: Seconds to wait before allowing recovery attempt (default 5.0)
        """
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self.failures = {}  # tool_name -> failure_count
        self.open_until = {}  # tool_name -> timestamp when circuit can close

    def record_failure(self, tool_name: str) -> None:
        """
        Record a failure for a tool.

        Increments failure count. If threshold reached, opens the circuit
        and sets cooldown expiration time.

        Args:
            tool_name: Name of the tool that failed
        """
        if tool_name not in self.failures:
            self.failures[tool_name] = 0

        self.failures[tool_name] += 1

        # Open circuit if threshold reached
        if self.failures[tool_name] >= self.failure_threshold:
            self.open(tool_name)

    def record_success(self, tool_name: str) -> None:
        """
        Record a success for a tool.

        Resets failure count and closes the circuit (removes open restriction).

        Args:
            tool_name: Name of the tool that succeeded
        """
        self.failures[tool_name] = 0
        if tool_name in self.open_until:
            del self.open_until[tool_name]

    def is_open(self, tool_name: str) -> bool:
        """
        Check if circuit is open (blocked) for a tool.

        A circuit is open if it was previously opened AND the cooldown
        period has not yet expired.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if circuit is open (tool is blocked), False otherwise
        """
        if tool_name not in self.open_until:
            return False

        current_time = time.time()
        if current_time < self.open_until[tool_name]:
            return True

        # Cooldown expired, close the circuit
        del self.open_until[tool_name]
        return False

    def open(self, tool_name: str) -> None:
        """
        Open the circuit for a tool.

        Prevents execution of the tool until cooldown period expires.

        Args:
            tool_name: Name of the tool to open
        """
        self.open_until[tool_name] = time.time() + self.cooldown
