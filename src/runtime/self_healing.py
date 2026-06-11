"""Self-healing controller for loop recovery."""

from src.runtime.safe_failure import make_safe_failure


class SelfHealingController:
    """Tracks failures and determines when self-healing should trigger.
    
    When failures reach the threshold, should_self_heal() returns True,
    indicating the loop should attempt self-healing (reset and restart).
    """

    def __init__(self, failure_threshold=3):
        """Initialize the controller.
        
        Args:
            failure_threshold: Number of failures before self-healing triggers.
        """
        self.failure_threshold = failure_threshold
        self.failure_count = 0

    def record_failure(self):
        """Record a failure."""
        self.failure_count += 1

    def record_success(self):
        """Record a success and reset failure count."""
        self.failure_count = 0

    def should_self_heal(self) -> bool:
        """Return whether self-healing should be triggered."""
        return self.failure_count >= self.failure_threshold


def perform_self_heal(loop_state):
    """Perform self-healing by resetting the loop state.
    
    Args:
        loop_state: The loop state object with a reset() method.
    
    Returns:
        A SafeFailure indicating successful self-healing.
    """
    loop_state.reset()
    return make_safe_failure(Exception("Loop self-healed"), {"self_healed": True})
