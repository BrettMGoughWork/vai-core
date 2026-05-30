"""
Contract tests for src.agent.dispatcher.AgentDispatcher.

Validates dispatch decision logic: bootstrap on first step, halt on
critical signals, halt after max iterations, reflect when last result present.
"""
import pytest

from src.agent.dispatcher import AgentDispatcher
from src.core.types.core_step import CoreStep
from src.core.signals.model import GovernedSignal, SignalSeverity, SignalType
from src.core.state.state import ConversationState
from src.core.types.result import CoreResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state(step_count=0, last_result=None):
    s = ConversationState(input="test")
    s.step_count = step_count
    s.last_result = last_result
    return s


def _signal(severity: SignalSeverity):
    return GovernedSignal(
        signal_type=SignalType.UNSAFE,
        severity=severity,
        confidence=1.0,
        source="test",
        payload={},
    )


# ── Dispatch contract ─────────────────────────────────────────────────────────

class TestAgentDispatcherContract:
    def test_first_step_returns_bootstrap(self):
        result = AgentDispatcher().dispatch(_state(step_count=0), signals=[])

        assert isinstance(result, CoreStep)
        assert result.step_type == "bootstrap"

    def test_bootstrap_step_includes_input_in_payload(self):
        state = ConversationState(input="my-prompt")
        state.step_count = 0

        result = AgentDispatcher().dispatch(state, signals=[])

        assert result.payload["input"] == "my-prompt"

    def test_critical_signal_halts_dispatch(self):
        result = AgentDispatcher().dispatch(
            _state(step_count=0),
            signals=[_signal(SignalSeverity.CRITICAL)],
        )

        assert result is None

    def test_non_critical_signal_does_not_halt(self):
        result = AgentDispatcher().dispatch(
            _state(step_count=0),
            signals=[_signal(SignalSeverity.WARN)],
        )

        assert result is not None

    def test_multiple_signals_critical_halts_even_with_non_critical(self):
        signals = [_signal(SignalSeverity.WARN), _signal(SignalSeverity.CRITICAL)]

        result = AgentDispatcher().dispatch(_state(step_count=0), signals=signals)

        assert result is None

    def test_step_count_over_five_returns_none(self):
        result = AgentDispatcher().dispatch(_state(step_count=6), signals=[])

        assert result is None

    def test_step_count_exactly_five_returns_none(self):
        # step_count > 5 → None, so 5 is not > 5 → should return something
        result = AgentDispatcher().dispatch(
            _state(step_count=5, last_result=CoreResult.from_text("ok")),
            signals=[],
        )
        # step_count=5 is NOT > 5, so we expect a reflect step
        assert result is not None
        assert result.step_type == "reflect"

    def test_with_last_result_returns_reflect_step(self):
        result = AgentDispatcher().dispatch(
            _state(step_count=1, last_result=CoreResult.from_text("answer")),
            signals=[],
        )

        assert isinstance(result, CoreStep)
        assert result.step_type == "reflect"

    def test_reflect_payload_contains_last_result_text(self):
        result = AgentDispatcher().dispatch(
            _state(step_count=1, last_result=CoreResult.from_text("final answer")),
            signals=[],
        )

        assert result.payload["last"] == "final answer"

    def test_no_last_result_mid_loop_returns_none(self):
        # step_count > 0, no last_result, no critical signals
        result = AgentDispatcher().dispatch(_state(step_count=1), signals=[])

        assert result is None
