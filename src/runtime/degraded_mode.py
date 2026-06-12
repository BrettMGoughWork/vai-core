"""Degraded mode controller for S1/S2 failure tracking and mode activation.

This module provides the lightweight S1/S2-level DegradedModeController used
by CoreStepExecutor to count consecutive failures and trigger degraded behaviour
within the execution step pipeline.

For S4 platform runtime (workers), see the more sophisticated implementation at:
    src.platform.runtime.safety.degraded_mode
which supports schema-compliant fallback output, escalation events, recovery
triggers (S1/S2/S3 signal gating), and a full behavioural contract.

Conceptual alignment with v2 semantics:
- Degraded Mode is a restricted execution state entered when instability is detected.
- While active, the controller forbids execution of multi-step reasoning, retries,
  and tool calls — the caller (CoreStepExecutor) is responsible for enforcement.
- Recovery requires explicit reset by the caller, who must verify S1 CoreStep
  pipeline stability before restoring normal execution.
"""


class DegradedModeController:
    """Tracks failures and activates degraded mode when threshold is reached.

    Once active, the controller remains active until explicitly reset by the caller.
    Failures continue to be counted while active.

    Conceptual contract (v2 behavioural alignment):
    - ❌ No retries (caller must not re-attempt work while active)
    - ❌ No multi-step reasoning (caller must short-circuit to fallback)
    - ❌ No tool calls (caller must avoid unsafe operations)
    - ✅ Wait for explicit reset via reset()
    - ✅ Maintain heartbeat (caller responsibility)
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
        """Record a success. Only resets failure count if not in degraded mode.

        Does not exit degraded mode — use reset() for that.
        """
        if not self.active:
            self.failure_count = 0

    def is_active(self):
        """Return whether degraded mode is currently active."""
        return self.active

    def reset(self):
        """Explicitly reset the controller back to normal operation.

        The caller MUST verify S1 CoreStep pipeline stability before calling
        this method, matching the v2 recovery contract requirement.
        """
        self.failure_count = 0
        self.active = False
