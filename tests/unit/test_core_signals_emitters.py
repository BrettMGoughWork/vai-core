import pytest

from src.core.signals.interface import evaluate_signals
from src.core.signals.emitters import (
    emit_stuck_from_subgoals,
    emit_drift_from_segments,
    emit_unsafe_from_runtime,
)
from src.core.signals.model import SignalType, SignalSeverity


# ------------------------------------------------------------
# Fake substrate states for deterministic testing
# ------------------------------------------------------------
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


# ============================================================
# INDIVIDUAL EMITTER TESTS
# ============================================================

# ------------------------------------------------------------
# STUCK EMITTER
# ------------------------------------------------------------
def test_emit_stuck_from_subgoals_detects_stuck():
    parent = FakeSubgoal("parent", created_at=200)
    leaf = FakeSubgoal("leaf", created_at=100)

    state = FakeSubgoalState([parent, leaf], idle_cycles=10)

    signals = emit_stuck_from_subgoals(state)

    assert len(signals) == 1
    s = signals[0]
    assert s.signal_type == SignalType.STUCK
    assert s.payload["leaf_subgoal_id"] == "leaf"
    assert s.payload["parent_subgoal_id"] == "parent"


def test_emit_stuck_from_subgoals_no_signal_when_not_stuck():
    parent = FakeSubgoal("parent", created_at=100)
    leaf = FakeSubgoal("leaf", created_at=200)

    state = FakeSubgoalState([parent, leaf], idle_cycles=0)

    signals = emit_stuck_from_subgoals(state)
    assert signals == []


# ------------------------------------------------------------
# DRIFT EMITTER
# ------------------------------------------------------------
def test_emit_drift_from_segments_detects_gaps():
    state = FakeSegmentState(gaps=[1], overlaps=[])

    signals = emit_drift_from_segments(state)

    assert len(signals) == 1
    s = signals[0]
    assert s.signal_type == SignalType.DRIFT
    assert s.payload["gaps"] == 1


def test_emit_drift_from_segments_detects_repeated_failures():
    state = FakeSegmentState(repeated_failures=5)

    signals = emit_drift_from_segments(state)

    assert len(signals) == 1
    s = signals[0]
    assert s.signal_type == SignalType.DRIFT
    assert s.payload["repeated_failures"] == 5


def test_emit_drift_from_segments_no_signal_when_clean():
    state = FakeSegmentState()

    signals = emit_drift_from_segments(state)
    assert signals == []


# ------------------------------------------------------------
# UNSAFE EMITTER
# ------------------------------------------------------------
def test_emit_unsafe_from_runtime_detects_unsafe():
    state = FakeRuntimeState(unsafe_conditions=["boom"])

    signals = emit_unsafe_from_runtime(state)

    assert len(signals) == 1
    s = signals[0]
    assert s.signal_type == SignalType.UNSAFE
    assert s.payload["conditions"] == ["boom"]


def test_emit_unsafe_from_runtime_no_signal_when_safe():
    state = FakeRuntimeState()

    signals = emit_unsafe_from_runtime(state)
    assert signals == []


# ============================================================
# UNIFIED INTERFACE TESTS
# ============================================================

def test_interface_emits_stuck_signal():
    parent = FakeSubgoal("parent", created_at=200)
    leaf = FakeSubgoal("leaf", created_at=100)

    subgoal_state = FakeSubgoalState([parent, leaf], idle_cycles=10)
    segment_state = FakeSegmentState()
    runtime_state = None

    signals = evaluate_signals(subgoal_state, segment_state, runtime_state)

    assert any(s.signal_type == SignalType.STUCK for s in signals)


def test_interface_emits_drift_signal_for_gaps():
    subgoal_state = FakeSubgoalState([])
    segment_state = FakeSegmentState(gaps=[1, 2])

    signals = evaluate_signals(subgoal_state, segment_state)

    assert any(s.signal_type == SignalType.DRIFT for s in signals)


def test_interface_emits_critical_drift_for_repeated_failures():
    subgoal_state = FakeSubgoalState([])
    segment_state = FakeSegmentState(repeated_failures=5)

    signals = evaluate_signals(subgoal_state, segment_state)

    drift = next(s for s in signals if s.signal_type == SignalType.DRIFT)
    assert drift.severity == SignalSeverity.CRITICAL


def test_interface_emits_unsafe_signal():
    subgoal_state = FakeSubgoalState([])
    segment_state = FakeSegmentState()
    runtime_state = FakeRuntimeState(unsafe_conditions=["bad"])

    signals = evaluate_signals(subgoal_state, segment_state, runtime_state)

    assert any(s.signal_type == SignalType.UNSAFE for s in signals)