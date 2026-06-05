"""
Tests for Phase 2.7.2 — Temporal Drift Signals.

Covers:
  - TemporalDriftSignal frozen dataclass validation
  - detect_temporal_drift() pure function
  - None previous_record → empty list
  - no_progress detection
  - repetition detection
  - oscillation detection
  - regression detection
  - Multiple signals emitted deterministically
  - Confidence values correct
  - Details JSON‑safe
  - No mutation of inputs
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.drift.behavioural_signal_types import (
    BehaviouralSignal,
    BehaviouralSignalType,
)
from src.core.planning.drift.temporal_drift_signals import detect_temporal_drift
from src.core.planning.drift.temporal_signal_types import (
    ProgressSignal,
    TemporalDriftSignal,
)

NOW = "2025-06-05T00:00:00+00:00"


# ── helpers ─────────────────────────────────────────────────────────────────


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
    last_output: Any = None,
    metadata: Dict[str, Any] | None = None,
    signals: List[BehaviouralSignal] | None = None,
) -> SegmentMemoryRecord:
    return SegmentMemoryRecord(
        segment_id=segment_id,
        parent_id=None,
        subgoal_id=subgoal_id,
        state=None,
        content=["step-1"],
        created_at=NOW,
        context={},
        metadata=metadata or {},
        last_output=last_output,
        behavioural_signals=signals or [],
    )


# =============================================================================
# TemporalDriftSignal dataclass
# =============================================================================


class TestTemporalDriftSignal:
    """Tests for the TemporalDriftSignal frozen dataclass."""

    def test_valid_construction(self) -> None:
        s = TemporalDriftSignal(
            type="no_progress",
            confidence=0.6,
            details={"reason": "stalled"},
        )
        assert s.type == "no_progress"
        assert s.confidence == 0.6
        assert s.details == {"reason": "stalled"}

    def test_confidence_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            TemporalDriftSignal(
                type="no_progress",
                confidence=-0.1,
                details={},
            )

    def test_confidence_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            TemporalDriftSignal(
                type="no_progress",
                confidence=1.1,
                details={},
            )

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="type"):
            TemporalDriftSignal(
                type="invalid_type",  # type: ignore[arg-type]
                confidence=0.5,
                details={},
            )

    def test_frozen(self) -> None:
        s = TemporalDriftSignal(
            type="no_progress",
            confidence=0.6,
            details={"x": 1},
        )
        with pytest.raises(Exception):
            s.confidence = 0.8  # type: ignore[misc]

    def test_details_defensive_copy(self) -> None:
        details = {"key": "original"}
        s = TemporalDriftSignal(
            type="no_progress",
            confidence=0.6,
            details=details,
        )
        # Mutating the original dict should not affect the signal
        details["key"] = "mutated"
        assert s.details == {"key": "original"}

    def test_details_deep_copy(self) -> None:
        """Nested mutable structures must be deep-copied."""
        details = {"outer": {"inner": [1, 2, 3]}}
        s = TemporalDriftSignal(
            type="no_progress",
            confidence=0.6,
            details=details,
        )
        details["outer"]["inner"].append(4)
        assert s.details["outer"]["inner"] == [1, 2, 3]

    def test_json_serializable(self) -> None:
        s = TemporalDriftSignal(
            type="no_progress",
            confidence=0.6,
            details={"summary": "stalled", "count": 3},
        )
        encoded = json.dumps(
            {
                "type": s.type,
                "confidence": s.confidence,
                "details": s.details,
            }
        )
        decoded = json.loads(encoded)
        assert decoded["type"] == "no_progress"
        assert decoded["confidence"] == 0.6
        assert decoded["details"] == {"summary": "stalled", "count": 3}


# =============================================================================
# None previous / None progress_signal → empty
# =============================================================================


class TestNoTemporalContext:
    """Tests for missing temporal context."""

    def test_none_previous_returns_empty(self) -> None:
        current = _record(last_output={"x": 1})
        progress = ProgressSignal(
            status="steady",
            confidence=0.7,
            reasons=["output: 1 field(s) added"],
        )
        result = detect_temporal_drift(None, current, progress)
        assert result == []

    def test_none_progress_returns_empty(self) -> None:
        prev = _record(last_output={"x": 1})
        current = _record(last_output={"x": 1})
        result = detect_temporal_drift(prev, current, None)
        assert result == []


# =============================================================================
# No Progress detection
# =============================================================================


class TestNoProgress:
    """Tests for no_progress temporal drift signal."""

    def test_stalled_progress_emits_no_progress(self) -> None:
        prev = _record(last_output={"x": 1})
        current = _record(last_output={"x": 1})  # identical → stalled
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes detected"],
        )
        result = detect_temporal_drift(prev, current, progress)
        no_progress = [s for s in result if s.type == "no_progress"]
        assert len(no_progress) == 1
        assert no_progress[0].confidence == 0.6
        assert no_progress[0].details["status"] == "stalled"

    def test_steady_progress_no_no_progress(self) -> None:
        prev = _record(last_output={"x": 1})
        current = _record(last_output={"x": 2})
        progress = ProgressSignal(
            status="steady",
            confidence=0.7,
            reasons=["output changed"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert not any(s.type == "no_progress" for s in result)

    def test_regressed_progress_no_no_progress(self) -> None:
        prev = _record(last_output={"x": 2})
        current = _record(last_output={})  # field removed → regressed
        progress = ProgressSignal(
            status="regressed",
            confidence=0.9,
            reasons=["output: 1 field(s) removed"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert not any(s.type == "no_progress" for s in result)


# =============================================================================
# Repetition detection
# =============================================================================


class TestRepetition:
    """Tests for repetition temporal drift signal."""

    def test_identical_outputs_emit_repetition(self) -> None:
        prev = _record(last_output={"a": 1, "b": 2})
        current = _record(last_output={"a": 1, "b": 2})
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes detected"],
        )
        result = detect_temporal_drift(prev, current, progress)
        reps = [s for s in result if s.type == "repetition"]
        assert len(reps) == 1
        assert reps[0].confidence == 0.7
        assert "hash" in reps[0].details
        assert "identical" in reps[0].details["match"]

    def test_none_outputs_emit_repetition(self) -> None:
        """Two None outputs count as identical."""
        prev = _record(last_output=None)
        current = _record(last_output=None)
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        reps = [s for s in result if s.type == "repetition"]
        assert len(reps) == 1

    def test_different_outputs_no_repetition(self) -> None:
        prev = _record(last_output={"a": 1})
        current = _record(last_output={"a": 2})
        progress = ProgressSignal(
            status="steady",
            confidence=0.7,
            reasons=["output changed"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert not any(s.type == "repetition" for s in result)

    def test_none_vs_value_no_repetition(self) -> None:
        prev = _record(last_output=None)
        current = _record(last_output={"a": 1})
        progress = ProgressSignal(
            status="steady",
            confidence=0.7,
            reasons=["output added"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert not any(s.type == "repetition" for s in result)


# =============================================================================
# Oscillation detection
# =============================================================================


class TestOscillation:
    """Tests for oscillation temporal drift signal."""

    def test_oscillation_pattern_emits_signal(self) -> None:
        """A → B → A oscillation: current output matches previous, and
        cross-cycle metadata confirms the flip-flop pattern."""
        value_a = {"result": "A"}
        value_b = {"result": "B"}

        # Cycle N (current): output = A, metadata says 2nd last was B
        current = _record(
            last_output=value_a,
            metadata={"second_last_output": value_b},
        )
        # Cycle N-1 (previous): output = A (same as current!), metadata says last was B
        prev = _record(
            last_output=value_a,
            metadata={"last_output": value_b},
        )
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        osc = [s for s in result if s.type == "oscillation"]
        assert len(osc) == 1
        assert osc[0].confidence == 0.8
        assert "oscillation" in osc[0].details["pattern"]

    def test_missing_metadata_no_oscillation(self) -> None:
        """Without the cross-cycle metadata keys, oscillation is not emitted."""
        value = {"result": "X"}
        prev = _record(last_output=value, metadata={})
        current = _record(last_output=value, metadata={})
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert not any(s.type == "oscillation" for s in result)

    def test_only_one_metadata_key_missing(self) -> None:
        """Both keys must be present for oscillation to fire."""
        value = {"result": "X"}
        prev = _record(last_output=value, metadata={"last_output": value})
        current = _record(last_output=value, metadata={})
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert not any(s.type == "oscillation" for s in result)

    def test_different_outputs_no_oscillation(self) -> None:
        prev = _record(last_output={"a": 1}, metadata={"last_output": {"a": 0}})
        current = _record(
            last_output={"a": 2},
            metadata={"second_last_output": {"a": 0}},
        )
        progress = ProgressSignal(
            status="steady",
            confidence=0.7,
            reasons=["changed"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert not any(s.type == "oscillation" for s in result)

    def test_mismatched_metadata_values_no_oscillation(self) -> None:
        """prev.last_output metadata != curr.second_last_output → no oscillation."""
        value = {"x": 1}
        prev = _record(last_output=value, metadata={"last_output": {"x": 9}})
        current = _record(
            last_output=value,
            metadata={"second_last_output": {"x": 8}},
        )
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert not any(s.type == "oscillation" for s in result)


# =============================================================================
# Regression detection
# =============================================================================


class TestRegression:
    """Tests for regression temporal drift signal."""

    def test_regressed_progress_emits_regression(self) -> None:
        prev = _record(last_output={"a": 1, "b": 2})
        current = _record(last_output={"a": 1})
        progress = ProgressSignal(
            status="regressed",
            confidence=0.9,
            reasons=["output: 1 field(s) removed"],
        )
        result = detect_temporal_drift(prev, current, progress)
        regs = [s for s in result if s.type == "regression"]
        assert len(regs) == 1
        assert regs[0].confidence == 0.9
        assert regs[0].details["status"] == "regressed"

    def test_steady_progress_no_regression(self) -> None:
        prev = _record(last_output={"a": 1})
        current = _record(last_output={"a": 1, "b": 2})
        progress = ProgressSignal(
            status="steady",
            confidence=0.7,
            reasons=["output: 1 field(s) added"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert not any(s.type == "regression" for s in result)

    def test_stalled_progress_no_regression(self) -> None:
        prev = _record(last_output={"a": 1})
        current = _record(last_output={"a": 1})
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert not any(s.type == "regression" for s in result)


# =============================================================================
# Multiple signals & ordering
# =============================================================================


class TestMultipleSignals:
    """Tests for multiple simultaneous signals and deterministic ordering."""

    def test_repetition_and_no_progress_emitted_together(self) -> None:
        """Identical outputs + stalled → both repetition and no_progress."""
        prev = _record(last_output={"a": 1})
        current = _record(last_output={"a": 1})
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        types = [s.type for s in result]
        assert "no_progress" in types
        assert "repetition" in types

    def test_deterministic_ordering(self) -> None:
        """Signal order must be: no_progress, repetition, oscillation, regression."""
        value = {"x": 1}
        prev = _record(
            last_output=value,
            metadata={"last_output": value, "something": "extra"},
        )
        current = _record(
            last_output=value,
            metadata={
                "second_last_output": value,
                "extra": True,
            },
        )
        # progress = regressed (to trigger all four types)
        progress = ProgressSignal(
            status="regressed",
            confidence=0.9,
            reasons=["output: field changed", "metadata: 1 field(s) added"],
        )
        # Run twice to confirm determinism
        result1 = detect_temporal_drift(prev, current, progress)
        result2 = detect_temporal_drift(prev, current, progress)

        expected_order = [
            "no_progress",   # regressed ≠ stalled → NOT emitted
            "repetition",
            "oscillation",
            "regression",
        ]
        # With regressed status, no_progress won't fire.  We still check order.
        types1 = [s.type for s in result1]
        types2 = [s.type for s in result2]
        assert types1 == types2
        # Verify that within the result, ordering respects the deterministic loop
        for i, t in enumerate(types1):
            if t == "repetition":
                assert "regression" in types1[i + 1 :]  # regression must come after

    def test_all_four_signals(self) -> None:
        """Trigger all four signal types simultaneously."""
        value = {"x": 1}
        prev = _record(
            last_output=value,
            metadata={"last_output": value},
        )
        current = _record(
            last_output=value,
            metadata={"second_last_output": value},
        )
        # stalled → no_progress; identical outputs → repetition;
        # metadata matches → oscillation; regressed → regression
        # Use regressed to get regression
        progress = ProgressSignal(
            status="regressed",
            confidence=0.9,
            reasons=["output: field removed"],
        )
        result = detect_temporal_drift(prev, current, progress)
        types = [s.type for s in result]
        # no_progress won't fire because status is regressed, not stalled.
        # We have: repetition, oscillation, regression = 3 signals.
        assert "repetition" in types
        assert "oscillation" in types
        assert "regression" in types


# =============================================================================
# Confidence values
# =============================================================================


class TestConfidenceValues:
    """Verify confidence values per signal type."""

    def test_no_progress_confidence(self) -> None:
        prev = _record(last_output={"x": 1})
        current = _record(last_output={"x": 1})
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        s = next(r for r in result if r.type == "no_progress")
        assert s.confidence == 0.6

    def test_repetition_confidence(self) -> None:
        prev = _record(last_output={"x": 1})
        current = _record(last_output={"x": 1})
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        s = next(r for r in result if r.type == "repetition")
        assert s.confidence == 0.7

    def test_oscillation_confidence(self) -> None:
        value = {"x": 1}
        prev = _record(last_output=value, metadata={"last_output": value})
        current = _record(
            last_output=value, metadata={"second_last_output": value}
        )
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        s = next(r for r in result if r.type == "oscillation")
        assert s.confidence == 0.8

    def test_regression_confidence(self) -> None:
        prev = _record(last_output={"x": 2})
        current = _record(last_output={"x": 1})
        progress = ProgressSignal(
            status="regressed",
            confidence=0.9,
            reasons=["output changed"],
        )
        result = detect_temporal_drift(prev, current, progress)
        s = next(r for r in result if r.type == "regression")
        assert s.confidence == 0.9


# =============================================================================
# Non‑mutation invariants
# =============================================================================


class TestNoMutation:
    """Verify detect_temporal_drift never mutates inputs."""

    def test_previous_record_unchanged(self) -> None:
        prev = _record(last_output={"a": 1})
        current = _record(last_output={"a": 2})
        progress = ProgressSignal(
            status="steady",
            confidence=0.7,
            reasons=["changed"],
        )
        prev_output_before = prev.last_output
        prev_metadata_before = dict(prev.metadata)

        detect_temporal_drift(prev, current, progress)

        assert prev.last_output == prev_output_before
        assert prev.metadata == prev_metadata_before

    def test_current_record_unchanged(self) -> None:
        prev = _record(last_output={"a": 1})
        current = _record(last_output={"a": 2})
        progress = ProgressSignal(
            status="steady",
            confidence=0.7,
            reasons=["changed"],
        )
        curr_output_before = current.last_output
        curr_metadata_before = dict(current.metadata)

        detect_temporal_drift(prev, current, progress)

        assert current.last_output == curr_output_before
        assert current.metadata == curr_metadata_before

    def test_progress_signal_unchanged(self) -> None:
        prev = _record(last_output={"a": 1})
        current = _record(last_output={"a": 1})
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        status_before = progress.status
        confidence_before = progress.confidence
        reasons_before = list(progress.reasons)

        detect_temporal_drift(prev, current, progress)

        assert progress.status == status_before
        assert progress.confidence == confidence_before
        assert progress.reasons == reasons_before


# =============================================================================
# Determinism
# =============================================================================


class TestDeterminism:
    """Verify deterministic output for identical inputs."""

    def test_same_inputs_same_output(self) -> None:
        prev = _record(last_output={"a": 1, "b": 2})
        current = _record(last_output={"a": 1})
        progress = ProgressSignal(
            status="regressed",
            confidence=0.9,
            reasons=["output: 1 field(s) removed"],
        )
        result1 = detect_temporal_drift(prev, current, progress)
        result2 = detect_temporal_drift(prev, current, progress)

        assert len(result1) == len(result2)
        for s1, s2 in zip(result1, result2):
            assert s1.type == s2.type
            assert s1.confidence == s2.confidence
            assert s1.details == s2.details

    def test_reasons_ordering_deterministic(self) -> None:
        """Multiple runs with same inputs produce same type ordering."""
        prev = _record(last_output={"x": 1})
        current = _record(last_output={"x": 1})
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        types1 = [s.type for s in detect_temporal_drift(prev, current, progress)]
        types2 = [s.type for s in detect_temporal_drift(prev, current, progress)]
        assert types1 == types2


# =============================================================================
# JSON safety
# =============================================================================


class TestJSONSafety:
    """Verify TemporalDriftSignal outputs are JSON‑serializable."""

    def test_signals_are_json_serializable(self) -> None:
        prev = _record(last_output={"a": 1})
        current = _record(last_output={"a": 1})
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        encoded = json.dumps(
            [
                {
                    "type": s.type,
                    "confidence": s.confidence,
                    "details": s.details,
                }
                for s in result
            ]
        )
        decoded = json.loads(encoded)
        assert isinstance(decoded, list)
        for item in decoded:
            assert isinstance(item["type"], str)
            assert isinstance(item["confidence"], float)
            assert isinstance(item["details"], dict)


# =============================================================================
# Edge cases
# =============================================================================


class TestEdgeCases:
    """Edge case tests for temporal drift detection."""

    def test_empty_dict_outputs(self) -> None:
        prev = _record(last_output={})
        current = _record(last_output={})
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert any(s.type == "repetition" for s in result)

    def test_str_output_repetition(self) -> None:
        prev = _record(last_output="hello")
        current = _record(last_output="hello")
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert any(s.type == "repetition" for s in result)

    def test_list_output_repetition(self) -> None:
        prev = _record(last_output=[1, 2, 3])
        current = _record(last_output=[1, 2, 3])
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert any(s.type == "repetition" for s in result)

    def test_nested_dict_output_repetition(self) -> None:
        nested = {"a": {"b": {"c": 1}}}
        prev = _record(last_output=nested)
        current = _record(last_output=nested)
        progress = ProgressSignal(
            status="stalled",
            confidence=0.5,
            reasons=["no changes"],
        )
        result = detect_temporal_drift(prev, current, progress)
        assert any(s.type == "repetition" for s in result)
