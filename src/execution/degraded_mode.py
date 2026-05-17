"""Degraded mode controller for failure tracking and mode activation."""


class DegradedModeController:
    """Tracks failures and activates degraded mode when threshold is reached.
    
    Once active, the controller remains active until explicitly reset by the caller.
    Failures continue to be counted while active.
    """

    def __init__(self, threshold=5):
        """Initialize the controller.
        
        Args:
            threshold: Number of failures before degraded mode activates.
        """
        self.threshold = threshold
        self.failure_count = 0
        self.active = False

    def record_failure(self):
        """Record a failure and check if threshold is reached."""
        self.failure_count += 1
        if self.failure_count >= self.threshold:
            self.active = True

    def record_success(self):
        """Record a success. Only resets failure count if not in degraded mode."""
        if not self.active:
            self.failure_count = 0

    def is_active(self):
        """Return whether degraded mode is currently active."""
        return self.active
