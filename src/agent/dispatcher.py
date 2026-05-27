from __future__ import annotations

from src.core.types.step import CoreStep
from src.core.signals.model import GovernedSignal, SignalSeverity
from src.core.state.state import ConversationState


class AgentDispatcher:
    """
    Minimal agent-level dispatcher (2.3.6).
    Chooses the next CoreStep based on:
    - current ConversationState
    - governed signals
    """

    def dispatch(
        self,
        state: ConversationState,
        signals: list[GovernedSignal],
    ) -> CoreStep | None:

        # 1. If any critical signals exist, stop immediately
        for s in signals:
            if s.severity == SignalSeverity.CRITICAL:
                return None

        # 2. If no steps have run yet, start with a bootstrap step
        if state.step_count == 0:
            return CoreStep(
                    step_type="bootstrap",
                    payload={"input": state.input}
            )
        
        # Stop after a few iterations
        if state.step_count > 5:
            return None

        # 3. Minimal behaviour: echo last result or noop
        if state.last_result is not None:
            return CoreStep(
                step_type="reflect",
                payload={"last": state.last_result.text},
            )

        # 4. Default: no more work
        return None