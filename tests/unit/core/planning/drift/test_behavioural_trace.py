"""
Tests for Phase 2.6.6 — Behavioural Trace.

Covers:
  - BehaviouralTrace frozen dataclass
  - build_behavioural_trace() pure function
  - Structural diff computation (output, metadata)
  - Side-effects delta from UNEXPECTED_SIDE_EFFECT signals
  - Signals and repair actions defensive-copied
  - Non-mutation of record, classification, and repair
  - Deterministic output
  - JSON-safe
  - Edge cases: None previous_record, empty values, no side-effects
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.drift.behavioural_signal_types import (
    BehaviouralDriftClassification,
    BehaviouralDriftRepair,
    BehaviouralSignal,
    BehaviouralSignalType,
)
from src.core.planning.drift.behavioural_trace import (
    _structural_diff,
    build_behavioural_trace,
)
from src.core.planning.drift.segment_trace_types import BehaviouralTrace


# ── helpers ─────────────────────────────────────────────────────────────────

NOW = "2025-06-05T00:00:00+00:00"


def _signal(
    signal_type: BehaviouralSignalType,
    segment_id: str = "seg-1",
    subgoal_id: str = "sg-1",
    details: Dict[str, Any] | None = None,
    timestamp: str = NOW,
) -> BehaviouralSignal:
    return BehaviouralSignal(
        signal_type=signal_type,
        segment_id=segment_id,
        subgoal_id=subgoal_id,
        details=details or {},
        timestamp=timestamp,
    )


def _record(
    *,
    segment_id: str = "seg-1",
    subgoal_id: str = "sg-1",
    signals: List[BehaviouralSignal] | None = None,
    metadata: Dict[str, Any] | None = None,
    last_output: Any = None,
    previous_output: Any = None,
    behavioural_delta: Optional[Dict[str, Any]] = None,
) -> SegmentMemoryRecord:
    return SegmentMemoryRecord(
        segment_id=segment_id,
        parent_id=None,
        subgoal_id=subgoal_id,
        state=None,
        content=["step-1"],
        created_at="2025-06-05T00:00:00+00:00",
        context={},
        metadata=metadata or {},
        last_output=last_output,
        previous_output=previous_output,
        behavioural_delta=behavioural_delta,
        behavioural_signals=signals or [],
    )


def _classification(
    drift_status: str = "no_drift",
    confidence: float = 0.0,
    reasons: List[BehaviouralSignal] | None = None,
) -> BehaviouralDriftClassification:
    return BehaviouralDriftClassification(
        drift_status=drift_status,  # type: ignore[arg-type]
        confidence=confidence,
        reasons=reasons or [],
    )


def _repair(
    needs_repair: bool = False,
    repair_actions: List[str] | None = None,
    confidence: float = 0.0,
    reasons: List[BehaviouralSignal] | None = None,
) -> BehaviouralDriftRepair:
    return BehaviouralDriftRepair(
        needs_repair=needs_repair,
        repair_actions=repair_actions or [],
        confidence=confidence,
        reasons=reasons or [],
    )


# ============================================================================
# Structural diff helper
# ============================================================================


class TestStructuralDiff:
    """Tests for the pure _structural_diff() helper."""

    def test_both_dicts_identical(self) -> None:
        d = {"a": 1, "b": 2}
        result = _structural_diff(d, d)
        assert result == {"added": {}, "removed": {}, "changed": {}}

    def test_key_added(self) -> None:
        result = _structural_diff({"a": 1}, {"a": 1, "b": 2})
        assert result == {"added": {"b": 2}, "removed": {}, "changed": {}}

    def test_key_removed(self) -> None:
        result = _structural_diff({"a": 1, "b": 2}, {"a": 1})
        assert result == {"added": {}, "removed": {"b": 2}, "changed": {}}

    def test_key_changed(self) -> None:
        result = _structural_diff({"a": 1, "b": 2}, {"a": 1, "b": 3})
        assert result == {
            "added": {},
            "removed": {},
            "changed": {"b": {"old": 2, "new": 3}},
        }

    def test_mixed_changes(self) -> None:
        result = _structural_diff(
            {"a": 1, "b": 2, "c": 3},
            {"a": 1, "b": 99, "d": 4},
        )
        assert result == {
            "added": {"d": 4},
            "removed": {"c": 3},
            "changed": {"b": {"old": 2, "new": 99}},
        }

    def test_non_dict_prev(self) -> None:
        result = _structural_diff(42, {"a": 1})
        assert result == {"previous": 42, "current": {"a": 1}}

    def test_non_dict_curr(self) -> None:
        result = _structural_diff({"a": 1}, [1, 2, 3])
        assert result == {"previous": {"a": 1}, "current": [1, 2, 3]}

    def test_none_values(self) -> None:
        result = _structural_diff(None, None)
        assert result == {"previous": None, "current": None}

    def test_empty_dicts(self) -> None:
        result = _structural_diff({}, {})
        assert result == {"added": {}, "removed": {}, "changed": {}}


# ============================================================================
# BehaviouralTrace dataclass
# ============================================================================


class TestBehaviouralTrace:
    """Tests for the BehaviouralTrace frozen dataclass."""

    def test_construction_empty(self) -> None:
        trace = BehaviouralTrace(
            behavioural_deltas={},
            behavioural_drift_signals=[],
            behavioural_repair_actions=[],
        )
        assert trace.behavioural_deltas == {}
        assert trace.behavioural_drift_signals == []
        assert trace.behavioural_repair_actions == []

    def test_construction_with_data(self) -> None:
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        trace = BehaviouralTrace(
            behavioural_deltas={"output_delta": {"changed": {}}},
            behavioural_drift_signals=[sig],
            behavioural_repair_actions=["verify declared vs executed capability"],
        )
        assert trace.behavioural_drift_signals == [sig]
        assert len(trace.behavioural_repair_actions) == 1

    def test_frozen(self) -> None:
        trace = BehaviouralTrace(
            behavioural_deltas={},
            behavioural_drift_signals=[],
            behavioural_repair_actions=[],
        )
        with pytest.raises(Exception):
            trace.behavioural_deltas = {}  # type: ignore[misc]

    def test_signals_defensive_copy(self) -> None:
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        signals_list = [sig]
        trace = BehaviouralTrace(
            behavioural_deltas={},
            behavioural_drift_signals=signals_list,
            behavioural_repair_actions=[],
        )
        signals_list.clear()
        assert len(trace.behavioural_drift_signals) == 1

    def test_actions_defensive_copy(self) -> None:
        actions = ["action-a"]
        trace = BehaviouralTrace(
            behavioural_deltas={},
            behavioural_drift_signals=[],
            behavioural_repair_actions=actions,
        )
        actions.clear()
        assert len(trace.behavioural_repair_actions) == 1

    def test_deltas_defensive_copy(self) -> None:
        deltas = {"output_delta": {"added": {"x": 1}}}
        trace = BehaviouralTrace(
            behavioural_deltas=deltas,
            behavioural_drift_signals=[],
            behavioural_repair_actions=[],
        )
        deltas["output_delta"]["added"]["y"] = 2
        assert "y" not in trace.behavioural_deltas["output_delta"]["added"]  # type: ignore[index]

    def test_json_serialisable(self) -> None:
        trace = BehaviouralTrace(
            behavioural_deltas={
                "output_delta": {"added": {}, "removed": {}, "changed": {}},
                "metadata_delta": {"added": {}, "removed": {}, "changed": {}},
            },
            behavioural_drift_signals=[],
            behavioural_repair_actions=[],
        )
        payload = json.dumps({
            "behavioural_deltas": trace.behavioural_deltas,
            "behavioural_drift_signals": [
                {
                    "signal_type": s.signal_type.value,
                    "segment_id": s.segment_id,
                    "subgoal_id": s.subgoal_id,
                    "details": s.details,
                    "timestamp": s.timestamp,
                }
                for s in trace.behavioural_drift_signals
            ],
            "behavioural_repair_actions": trace.behavioural_repair_actions,
        })
        assert isinstance(payload, str)
        back = json.loads(payload)
        assert back["behavioural_deltas"] == trace.behavioural_deltas


# ============================================================================
# build_behavioural_trace()
# ============================================================================


class TestBuildBehaviouralTrace:
    """Tests for the build_behavioural_trace() pure function."""

    def test_output_delta_key_added(self) -> None:
        prev = _record(last_output={"x": 1})
        curr = _record(last_output={"x": 1, "y": 2})
        c = _classification()
        r = _repair()

        trace = build_behavioural_trace(prev, curr, c, r)
        assert trace.behavioural_deltas["output_delta"] == {
            "added": {"y": 2},
            "removed": {},
            "changed": {},
        }

    def test_output_delta_key_removed(self) -> None:
        prev = _record(last_output={"a": 1, "b": 2})
        curr = _record(last_output={"b": 2})
        c = _classification()
        r = _repair()

        trace = build_behavioural_trace(prev, curr, c, r)
        assert trace.behavioural_deltas["output_delta"]["removed"] == {"a": 1}

    def test_output_delta_key_changed(self) -> None:
        prev = _record(last_output={"a": 1})
        curr = _record(last_output={"a": 99})
        c = _classification()
        r = _repair()

        trace = build_behavioural_trace(prev, curr, c, r)
        assert trace.behavioural_deltas["output_delta"]["changed"] == {
            "a": {"old": 1, "new": 99}
        }

    def test_output_delta_none_previous(self) -> None:
        prev = _record(last_output=None)
        curr = _record(last_output={"result": True})
        c = _classification()
        r = _repair()

        trace = build_behavioural_trace(prev, curr, c, r)
        assert trace.behavioural_deltas["output_delta"] == {
            "previous": None,
            "current": {"result": True},
        }

    def test_metadata_delta_detected(self) -> None:
        prev = _record(metadata={"version": 1})
        curr = _record(metadata={"version": 2})
        c = _classification()
        r = _repair()

        trace = build_behavioural_trace(prev, curr, c, r)
        assert trace.behavioural_deltas["metadata_delta"]["changed"] == {
            "version": {"old": 1, "new": 2}
        }

    def test_metadata_delta_identical(self) -> None:
        prev = _record(metadata={"v": 1})
        curr = _record(metadata={"v": 1})
        c = _classification()
        r = _repair()

        trace = build_behavioural_trace(prev, curr, c, r)
        assert trace.behavioural_deltas["metadata_delta"] == {
            "added": {},
            "removed": {},
            "changed": {},
        }

    def test_side_effects_delta_present(self) -> None:
        sig = _signal(
            BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT,
            details={"declared": [], "actual": ["file_write"]},
        )
        c = _classification(
            drift_status="behavioural_drift",
            confidence=0.25,
            reasons=[sig],
        )
        r = _repair(
            needs_repair=True,
            repair_actions=["audit side-effect declarations vs execution"],
            confidence=0.25,
            reasons=[sig],
        )
        curr = _record()

        trace = build_behavioural_trace(None, curr, c, r)
        assert "side_effects_delta" in trace.behavioural_deltas
        assert trace.behavioural_deltas["side_effects_delta"] == {
            "declared": [],
            "actual": ["file_write"],
        }

    def test_no_side_effects_delta_when_no_signal(self) -> None:
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        c = _classification(
            drift_status="behavioural_drift",
            confidence=0.25,
            reasons=[sig],
        )
        r = _repair(needs_repair=True, repair_actions=["a"], confidence=0.25, reasons=[sig])
        curr = _record()

        trace = build_behavioural_trace(None, curr, c, r)
        assert "side_effects_delta" not in trace.behavioural_deltas

    def test_signals_copied_from_classification(self) -> None:
        sig1 = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        sig2 = _signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE)
        c = _classification(
            drift_status="behavioural_drift",
            confidence=0.5,
            reasons=[sig1, sig2],
        )
        r = _repair(
            needs_repair=True,
            repair_actions=["a", "b"],
            confidence=0.5,
            reasons=[sig1, sig2],
        )
        curr = _record()

        trace = build_behavioural_trace(None, curr, c, r)
        assert len(trace.behavioural_drift_signals) == 2
        assert trace.behavioural_drift_signals[0].signal_type == BehaviouralSignalType.WRONG_CAPABILITY
        assert trace.behavioural_drift_signals[1].signal_type == BehaviouralSignalType.WRONG_OUTPUT_SHAPE

    def test_repair_actions_copied(self) -> None:
        c = _classification()
        r = _repair(
            needs_repair=True,
            repair_actions=["verify declared vs executed capability"],
            confidence=0.25,
            reasons=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)],
        )
        curr = _record()

        trace = build_behavioural_trace(None, curr, c, r)
        assert trace.behavioural_repair_actions == [
            "verify declared vs executed capability"
        ]

    def test_no_drift_trace_still_built(self) -> None:
        """Trace is built even when no drift is present — deltas are still computed."""
        prev = _record(last_output={"a": 1}, metadata={"v": 1})
        curr = _record(last_output={"a": 2}, metadata={"v": 1})
        c = _classification()  # no_drift, no reasons
        r = _repair()          # no repair

        trace = build_behavioural_trace(prev, curr, c, r)
        assert trace.behavioural_drift_signals == []
        assert trace.behavioural_repair_actions == []
        assert trace.behavioural_deltas["output_delta"]["changed"] == {
            "a": {"old": 1, "new": 2}
        }

    def test_does_not_mutate_record(self) -> None:
        prev = _record(last_output={"x": 1})
        curr = _record(last_output={"x": 2})
        c = _classification()
        r = _repair()

        prev_id_before = id(prev)
        curr_id_before = id(curr)

        build_behavioural_trace(prev, curr, c, r)

        assert id(prev) == prev_id_before
        assert id(curr) == curr_id_before
        assert prev.last_output == {"x": 1}
        assert curr.last_output == {"x": 2}

    def test_does_not_mutate_classification(self) -> None:
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        c = _classification(
            drift_status="behavioural_drift",
            confidence=0.25,
            reasons=[sig],
        )
        r = _repair(needs_repair=True, repair_actions=["a"], confidence=0.25, reasons=[sig])
        curr = _record()

        reasons_before = list(c.reasons)
        build_behavioural_trace(None, curr, c, r)
        assert list(c.reasons) == reasons_before

    def test_does_not_mutate_repair(self) -> None:
        c = _classification()
        r = _repair(
            needs_repair=True,
            repair_actions=["action-1"],
            confidence=0.5,
            reasons=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)],
        )
        curr = _record()

        actions_before = list(r.repair_actions)
        build_behavioural_trace(None, curr, c, r)
        assert list(r.repair_actions) == actions_before

    def test_deterministic_output(self) -> None:
        prev = _record(last_output={"a": 1})
        curr = _record(last_output={"a": 2})
        c = _classification()
        r = _repair()

        trace1 = build_behavioural_trace(prev, curr, c, r)
        trace2 = build_behavioural_trace(prev, curr, c, r)

        assert trace1.behavioural_deltas == trace2.behavioural_deltas
        assert trace1.behavioural_drift_signals == trace2.behavioural_drift_signals
        assert trace1.behavioural_repair_actions == trace2.behavioural_repair_actions

    def test_none_previous_record_handled(self) -> None:
        """When previous_record is None, deltas use None/{} as previous."""
        curr = _record(last_output={"result": "ok"}, metadata={"cycle": 1})
        c = _classification()
        r = _repair()

        trace = build_behavioural_trace(None, curr, c, r)

        assert trace.behavioural_deltas["output_delta"] == {
            "previous": None,
            "current": {"result": "ok"},
        }
        assert trace.behavioural_deltas["metadata_delta"] == {
            "added": {"cycle": 1},
            "removed": {},
            "changed": {},
        }

    def test_empty_outputs_both_none(self) -> None:
        prev = _record(last_output=None)
        curr = _record(last_output=None)
        c = _classification()
        r = _repair()

        trace = build_behavioural_trace(prev, curr, c, r)
        assert trace.behavioural_deltas["output_delta"] == {
            "previous": None,
            "current": None,
        }

    def test_json_serialisable_trace(self) -> None:
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        prev = _record(last_output={"x": 1})
        curr = _record(last_output={"x": 2})
        c = _classification(
            drift_status="behavioural_drift",
            confidence=0.25,
            reasons=[sig],
        )
        r = _repair(
            needs_repair=True,
            repair_actions=["verify declared vs executed capability"],
            confidence=0.25,
            reasons=[sig],
        )

        trace = build_behavioural_trace(prev, curr, c, r)

        serialised = {
            "behavioural_deltas": trace.behavioural_deltas,
            "behavioural_drift_signals": [
                {
                    "signal_type": s.signal_type.value,
                    "segment_id": s.segment_id,
                    "subgoal_id": s.subgoal_id,
                    "details": s.details,
                    "timestamp": s.timestamp,
                }
                for s in trace.behavioural_drift_signals
            ],
            "behavioural_repair_actions": trace.behavioural_repair_actions,
        }
        payload = json.dumps(serialised)
        assert isinstance(payload, str)
        back = json.loads(payload)
        assert back["behavioural_repair_actions"] == [
            "verify declared vs executed capability"
        ]

    def test_nested_output_delta(self) -> None:
        """Test that nested dict values are diffed structurally."""
        prev = _record(last_output={"nested": {"inner": 1}})
        curr = _record(last_output={"nested": {"inner": 2}})
        c = _classification()
        r = _repair()

        trace = build_behavioural_trace(prev, curr, c, r)
        # Nested dicts are compared by value (shallow dict diff),
        # so "nested" shows as changed with old/new values.
        od = trace.behavioural_deltas["output_delta"]
        assert "nested" in od["changed"]
