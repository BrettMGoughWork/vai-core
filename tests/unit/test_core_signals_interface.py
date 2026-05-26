import pytest

from src.core.signals.interface import evaluate_signals
from src.core.signals.model import SignalType, SignalSeverity

# Fake substrate states for deterministic testing
class FakeSubgoal:
    def __init__(self, subgoal_id, created_at):
        self.subgoal_id = subgoal_id
        self.created_at = created_at


class FakeSubgoalState:
    def __init__(self, chain, idle_cycles=0):
        self._chain = chain
        self.idle_cycles = idle_cycles

    def active_chain(self):
        return self._chain


class FakeSegmentState:
    def __init__(self, gaps=None, overlaps=None, repeated_failures=0):
        self.gaps = gaps or []
        self.overlaps = overlaps or []
        self.repeated_failures = repeated_failures

    @property
    def has_gaps(self):
        return len(self.gaps) > 0

    @property
    def has_overlaps(self):
        return len(self.overlaps) > 0


class FakeRuntimeState:
    def __init__(self, unsafe_conditions=None):
        self.unsafe_conditions = unsafe_conditions or []


# ------------------------------------------------------------
# STUCK SIGNAL TEST
# ------------------------------------------------------------
def test_interface_emits_stuck_signal():
    parent = FakeSubgoal("parent", created_at=200)
    leaf = FakeSubgoal("leaf", created_at=100)

    subgoal_state = FakeSubgoalState([parent, leaf], idle_cycles=10)
    segment_state = FakeSegmentState()
    runtime_state = None

    signals = evaluate_signals(subgoal_state, segment_state, runtime_state)

    assert any(s.signal_type == SignalType.STUCK for s in signals)
    stuck = next(s for s in signals if s.signal_type == SignalType.STUCK)

    assert stuck.severity == SignalSeverity.WARN
    assert stuck.payload["leaf_subgoal_id"] == "leaf"
    assert stuck.payload["parent_subgoal_id"] == "parent"


# ------------------------------------------------------------
# DRIFT SIGNAL TEST
# ------------------------------------------------------------
def test_interface_emits_drift_signal_for_gaps():
    subgoal_state = FakeSubgoalState([])
    segment_state = FakeSegmentState(gaps=[1, 2], overlaps=[], repeated_failures=0)

    signals = evaluate_signals(subgoal_state, segment_state)

    assert any(s.signal_type == SignalType.DRIFT for s in signals)
    drift = next(s for s in signals if s.signal_type == SignalType.DRIFT)

    assert drift.severity == SignalSeverity.WARN
    assert drift.payload["gaps"] == 2


def test_interface_emits_critical_drift_for_repeated_failures():
    subgoal_state = FakeSubgoalState([])
    segment_state = FakeSegmentState(repeated_failures=5)

    signals = evaluate_signals(subgoal_state, segment_state)

    assert any(s.signal_type == SignalType.DRIFT for s in signals)
    drift = next(s for s in signals if s.signal_type == SignalType.DRIFT)

    assert drift.severity == SignalSeverity.CRITICAL
    assert drift.payload["repeated_failures"] == 5


# ------------------------------------------------------------
# UNSAFE SIGNAL TEST
# ------------------------------------------------------------
def test_interface_emits_unsafe_signal():
    subgoal_state = FakeSubgoalState([])
    segment_state = FakeSegmentState()
    runtime_state = FakeRuntimeState(unsafe_conditions=["bad_thing"])

    signals = evaluate_signals(subgoal_state, segment_state, runtime_state)

    assert any(s.signal_type == SignalType.UNSAFE for s in signals)
    unsafe = next(s for s in signals if s.signal_type == SignalType.UNSAFE)

    assert unsafe.severity == SignalSeverity.CRITICAL
    assert unsafe.payload["conditions"] == ["bad_thing"]