"""
Signal classifier and GovernedSignal model tests.

Covers:
- GovernedSignal construction and immutability
- classify_drift(): threshold behaviour and payload contents
- classify_stuck(): idle cycle threshold and payload
- classify_unsafe(): event count threshold and payload
"""
import pytest

from src.core.signals.model import GovernedSignal, SignalType, SignalSeverity
from src.core.signals.classifier import (
    classify_drift,
    classify_stuck,
    classify_unsafe,
    MAX_SEGMENT_FAILURES,
    MAX_IDLE_CYCLES,
    MAX_UNSAFE_EVENTS,
)


# ── GovernedSignal model ──────────────────────────────────────────────────────

class TestGovernedSignal:
    def _signal(self, **kwargs):
        defaults = dict(
            signal_type=SignalType.DRIFT,
            severity=SignalSeverity.WARN,
            confidence=0.5,
            source="test",
            payload={},
        )
        defaults.update(kwargs)
        return GovernedSignal(**defaults)

    def test_basic_construction(self):
        sig = self._signal()
        assert sig.signal_type == SignalType.DRIFT
        assert sig.severity == SignalSeverity.WARN
        assert sig.confidence == 0.5
        assert sig.source == "test"
        assert sig.payload == {}

    def test_timestamp_is_auto_assigned(self):
        sig = self._signal()
        assert isinstance(sig.timestamp, int)
        assert sig.timestamp > 0

    def test_is_frozen(self):
        sig = self._signal()
        with pytest.raises(Exception):
            sig.source = "mutated"  # noqa: frozen dataclass

    def test_non_json_pure_payload_raises(self):
        with pytest.raises(TypeError):
            self._signal(payload={"bad": set([1, 2, 3])})

    def test_all_signal_types_constructable(self):
        for stype in SignalType:
            sig = self._signal(signal_type=stype)
            assert sig.signal_type == stype

    def test_all_severities_constructable(self):
        for sev in SignalSeverity:
            sig = self._signal(severity=sev)
            assert sig.severity == sev


# ── classify_drift() ──────────────────────────────────────────────────────────

class TestClassifyDrift:
    def test_returns_none_when_all_zero(self):
        result = classify_drift(repeated_failures=0, gaps=0, overlaps=0)
        assert result is None

    def test_repeated_failures_at_threshold_returns_none(self):
        # threshold is > MAX_SEGMENT_FAILURES, not >=
        result = classify_drift(repeated_failures=MAX_SEGMENT_FAILURES)
        assert result is None

    def test_repeated_failures_above_threshold_returns_critical(self):
        result = classify_drift(repeated_failures=MAX_SEGMENT_FAILURES + 1)

        assert result is not None
        assert result.signal_type == SignalType.DRIFT
        assert result.severity == SignalSeverity.CRITICAL
        assert result.confidence == 0.9
        assert result.source == "segments"

    def test_critical_payload_contains_repeated_failures(self):
        count = MAX_SEGMENT_FAILURES + 2
        result = classify_drift(repeated_failures=count)

        assert result.payload["repeated_failures"] == count

    def test_gaps_above_zero_returns_warn(self):
        result = classify_drift(gaps=1)

        assert result is not None
        assert result.signal_type == SignalType.DRIFT
        assert result.severity == SignalSeverity.WARN
        assert result.confidence == 0.7

    def test_overlaps_above_zero_returns_warn(self):
        result = classify_drift(overlaps=2)

        assert result is not None
        assert result.severity == SignalSeverity.WARN

    def test_warn_payload_contains_gaps_and_overlaps(self):
        result = classify_drift(gaps=3, overlaps=1)

        assert result.payload["gaps"] == 3
        assert result.payload["overlaps"] == 1

    def test_critical_takes_priority_over_gaps(self):
        # If repeated_failures exceeds threshold AND gaps > 0, critical is returned first
        result = classify_drift(repeated_failures=MAX_SEGMENT_FAILURES + 1, gaps=5)

        assert result.severity == SignalSeverity.CRITICAL

    def test_repeated_failures_one_below_threshold_with_gaps_returns_warn(self):
        result = classify_drift(repeated_failures=MAX_SEGMENT_FAILURES, gaps=1)

        assert result.severity == SignalSeverity.WARN


# ── classify_stuck() ─────────────────────────────────────────────────────────

class TestClassifyStuck:
    def test_returns_none_when_idle_cycles_at_threshold(self):
        result = classify_stuck(idle_cycles=MAX_IDLE_CYCLES, leaf_id="leaf", parent_id="parent")
        assert result is None

    def test_returns_none_when_idle_cycles_zero(self):
        result = classify_stuck(idle_cycles=0, leaf_id="l", parent_id="p")
        assert result is None

    def test_returns_warn_when_idle_cycles_above_threshold(self):
        result = classify_stuck(
            idle_cycles=MAX_IDLE_CYCLES + 1, leaf_id="leaf-1", parent_id="parent-1"
        )

        assert result is not None
        assert result.signal_type == SignalType.STUCK
        assert result.severity == SignalSeverity.WARN
        assert result.confidence == 0.6
        assert result.source == "subgoals"

    def test_payload_contains_leaf_parent_and_idle_cycles(self):
        result = classify_stuck(
            idle_cycles=MAX_IDLE_CYCLES + 3, leaf_id="leaf-abc", parent_id="parent-xyz"
        )

        assert result.payload["leaf_subgoal_id"] == "leaf-abc"
        assert result.payload["parent_subgoal_id"] == "parent-xyz"
        assert result.payload["idle_cycles"] == MAX_IDLE_CYCLES + 3

    def test_boundary_one_above_threshold(self):
        result = classify_stuck(idle_cycles=MAX_IDLE_CYCLES + 1, leaf_id="l", parent_id="p")
        assert result is not None

    def test_boundary_exactly_at_threshold_returns_none(self):
        result = classify_stuck(idle_cycles=MAX_IDLE_CYCLES, leaf_id="l", parent_id="p")
        assert result is None


# ── classify_unsafe() ────────────────────────────────────────────────────────

class TestClassifyUnsafe:
    def test_returns_none_when_zero_events(self):
        result = classify_unsafe(unsafe_events=0, conditions={})
        assert result is None

    def test_returns_critical_at_threshold(self):
        # threshold is >= MAX_UNSAFE_EVENTS
        result = classify_unsafe(unsafe_events=MAX_UNSAFE_EVENTS, conditions={})

        assert result is not None
        assert result.signal_type == SignalType.UNSAFE
        assert result.severity == SignalSeverity.CRITICAL
        assert result.confidence == 1.0
        assert result.source == "runtime"

    def test_returns_critical_above_threshold(self):
        result = classify_unsafe(unsafe_events=MAX_UNSAFE_EVENTS + 5, conditions={})
        assert result is not None
        assert result.severity == SignalSeverity.CRITICAL

    def test_conditions_passed_through_to_payload(self):
        conditions = {"memory": "exceeded", "cpu": "overload"}
        result = classify_unsafe(unsafe_events=1, conditions=conditions)

        assert result.payload["conditions"] == conditions

    def test_empty_conditions_dict_is_valid(self):
        result = classify_unsafe(unsafe_events=1, conditions={})
        assert result.payload["conditions"] == {}