from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Iterable

from src.core.state.state import ConversationState
from src.core.signals.interface import evaluate_signals
from src.core.signals.model import GovernedSignal, SignalSeverity
from src.core.planning.dispatch.safe_step_dispatcher import SafeStepDispatcher
from src.core.state.core_step_executor import CoreStepExecutor
from src.core.types.errors import AgentError

@dataclass
class AgentLoopConfig:
    """Configuration for the minimal agent loop."""
    max_steps: int = 50
    stop_on_critical: bool = True


class AgentLoop:
    """
    Minimal agent loop (2.3.6).
    - Reads substrate state
    - Evaluates governed signals
    - Dispatches next step
    - Executes step
    - Updates state
    - Loops
    """

    def __init__(
        self,
        dispatcher: SafeStepDispatcher,
        engine: CoreStepExecutor,
        config: Optional[AgentLoopConfig] = None,
    ):
        self.dispatcher = dispatcher
        self.engine = engine
        self.config = config or AgentLoopConfig()

    def run(self, state: ConversationState) -> ConversationState:
        """
        Run the minimal agent loop until:
        - max steps reached
        - critical signal encountered (configurable)
        - dispatcher returns None (no-op)
        """
        for _ in range(self.config.max_steps):

            # 1. Evaluate governed signals
            signals: Iterable[GovernedSignal] = evaluate_signals(
                state.subgoal_state,
                state.segment_state,
            )

            # 2. Handle critical signals
            critical = self._first_critical(signals)
            if critical:
                if self.config.stop_on_critical:
                    return self._handle_critical(state, critical)
                # else: fall through to dispatcher

            # 3. Ask dispatcher for next step
            step = self.dispatcher.dispatch(state, signals)

            print("DISPATCHED STEP:", step)

            if step is None:
                # No more work to do
                return state

            # 4. Execute step
            try:
                result = self.engine.execute(step)

                state = state.apply_step_result(result)
                
                print("STEP", state.step_count, "RESULT:", result)

            except Exception as exc:
                # Wrap into governed signal and stop
                return self._handle_execution_error(state, exc)

            # 5. Update state
            state = state.apply_step_result(result)

        return state # max steps reached

    # ---------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------

    @staticmethod
    def _first_critical(signals: Iterable[GovernedSignal]) -> Optional[GovernedSignal]:
        for s in signals:
            if s.severity == SignalSeverity.CRITICAL:
                return s
        return None

    def _handle_critical(self, state: ConversationState, signal: GovernedSignal) -> ConversationState:
        # Placeholder for reflection hooks (2.5.x)
        # For now: stop immediately
        return state.with_termination_reason(f"critical-signal:{signal.signal_type}")

    def _handle_execution_error(self, state: ConversationState, exc: Exception) -> ConversationState:
        # Convert to governed signal (placeholder)
        wrapped = AgentError.from_exception(exc)
        return state.with_termination_reason(f"execution-error:{wrapped.code}")