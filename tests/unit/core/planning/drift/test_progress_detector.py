"""
Tests for Phase 2.7.1 — Progress Detector.

Covers:
  - ProgressSignal frozen dataclass validation
  - detect_progress() pure function
  - None previous → None
  - Steady / stalled / regressed detection
  - Confidence values per status
  - Deterministic reasons
  - Non‑mutation invariants
  - JSON‑safe output
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
from src.core.planning.drift.progress_detector import detect_progress
from src.core.planning.drift.temporal_signal_types import ProgressSignal

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
# ProgressSignal dataclass
# =============================================================================


class TestProgressSignal:
    """Tests for the ProgressSignal frozen dataclass."""

    def test_steady_construction(self) -> None:
        p = ProgressSignal(
            status="steady",
            confidence=0.7,
            reasons=["output: 1 field(s) added"],
        )
        assert p.status == "steady"
        assert p.confidence == 0.7
        assert p.reasons == ["output: 1 field(s) added"]

    def test_stalled_construction(self) -> None:
        p = ProgressSignal(status="stalled", confidence=0.5, reasons=[])
        assert p.status == "stalled"
        assert p.confidence == 0.5
        assert p.reasons == []

    def test_regressed_construction(self) -> None:
        p = ProgressSignal(
            status="regressed",
            confidence=0.9,
            reasons=["output: 2 field(s) removed"],
        )
        assert p.status == "regressed"
        assert p.confidence == 0.9

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProgressSignal(status="unknown", confidence=0.5, reasons=[])  # type: ignore[arg-type]

    def test_confidence_below_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProgressSignal(status="steady", confidence=-0.1, reasons=[])

    def test_confidence_above_one_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProgressSignal(status="steady", confidence=1.1, reasons=[])

    def test_frozen(self) -> None:
        p = ProgressSignal(status="steady", confidence=0.7, reasons=["a"])
        with pytest.raises(Exception):
            p.status = "stalled"  # type: ignore[misc]

    def test_reasons_defensive_copy(self) -> None:
        reasons = ["reason a", "reason b"]
        p = ProgressSignal(status="steady", confidence=0.7, reasons=reasons)
        reasons.append("reason c")
        assert p.reasons == ["reason a", "reason b"]

    def test_json_serializable(self) -> None:
        p = ProgressSignal(status="steady", confidence=0.7, reasons=["a", "b"])
        data = json.dumps(
            {"status": p.status, "confidence": p.confidence, "reasons": p.reasons}
        )
        roundtrip = json.loads(data)
        assert roundtrip["status"] == "steady"
        assert roundtrip["confidence"] == 0.7

    def test_json_rejects_non_serializable(self) -> None:
        with pytest.raises((TypeError, ValueError)):
            ProgressSignal(status="steady", confidence=0.7, reasons=[object()])  # type: ignore[list-item]


# =============================================================================
# detect_progress — None previous
# =============================================================================


class TestDetectProgressNoPrevious:
    """Tests for detect_progress when previous_record is None."""

    def test_none_previous_returns_none(self) -> None:
        current = _record(last_output={"x": 1})
        result = detect_progress(None, current)
        assert result is None

    def test_none_previous_with_output(self) -> None:
        current = _record(last_output={"a": 1, "b": 2})
        result = detect_progress(None, current)
        assert result is None


# =============================================================================
# detect_progress — stalled detection
# =============================================================================


class TestDetectProgressStalled:
    """Tests for stalled progress detection."""

    def test_identical_output_dict(self) -> None:
        prev = _record(last_output={"x": 1, "y": 2})
        curr = _record(last_output={"x": 1, "y": 2})
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "stalled"
        assert result.confidence == 0.5
        assert result.reasons == []

    def test_identical_output_none(self) -> None:
        prev = _record(last_output=None)
        curr = _record(last_output=None)
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "stalled"
        assert result.confidence == 0.5

    def test_identical_simple_value(self) -> None:
        prev = _record(last_output="hello")
        curr = _record(last_output="hello")
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "stalled"

    def test_identical_metadata(self) -> None:
        prev = _record(last_output={"x": 1}, metadata={"v": 2.0})
        curr = _record(last_output={"x": 1}, metadata={"v": 2.0})
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "stalled"

    def test_balanced_changes_stalled(self) -> None:
        """Equal additions and removals → stalled (no net progress)."""
        prev = _record(last_output={"keep": 1, "remove_me": 2})
        curr = _record(last_output={"keep": 1, "new_field": 3})
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "stalled"

    def test_no_outputs_no_metadata(self) -> None:
        prev = _record()
        curr = _record()
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "stalled"


# =============================================================================
# detect_progress — steady detection
# =============================================================================


class TestDetectProgressSteady:
    """Tests for steady progress detection."""

    def test_output_fields_added(self) -> None:
        prev = _record(last_output={"x": 1})
        curr = _record(last_output={"x": 1, "y": 2, "z": 3})
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "steady"
        assert result.confidence == 0.7
        assert "output: 2 field(s) added" in result.reasons

    def test_metadata_fields_added(self) -> None:
        prev = _record(last_output={"x": 1}, metadata={"v": 1})
        curr = _record(last_output={"x": 1}, metadata={"v": 1, "w": 2})
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "steady"
        assert "metadata: 1 field(s) added" in result.reasons

    def test_more_additions_than_removals(self) -> None:
        prev = _record(last_output={"keep": 1, "old": 2})
        curr = _record(last_output={"keep": 1, "new_a": 3, "new_b": 4})
        # 1 removed (old), 2 added (new_a, new_b) → net positive → steady
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "steady"

    def test_none_to_value_steady(self) -> None:
        prev = _record(last_output=None)
        curr = _record(last_output="result")
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "steady"
        assert result.confidence == 0.7

    def test_fewer_side_effects(self) -> None:
        """Fewer side effects between cycles → steady (progress)."""
        prev = _record(
            last_output={"x": 1},
            signals=[_signal(BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT)],
        )
        curr = _record(last_output={"x": 1}, signals=[])
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "steady"
        assert any("side effects" in r for r in result.reasons)


# =============================================================================
# detect_progress — regressed detection
# =============================================================================


class TestDetectProgressRegressed:
    """Tests for regressed progress detection."""

    def test_output_fields_removed(self) -> None:
        prev = _record(last_output={"x": 1, "y": 2, "z": 3})
        curr = _record(last_output={"x": 1})
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "regressed"
        assert result.confidence == 0.9
        assert "output: 2 field(s) removed" in result.reasons

    def test_output_fields_changed(self) -> None:
        prev = _record(last_output={"x": 1, "y": 2})
        curr = _record(last_output={"x": 1, "y": 99})
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "regressed"
        assert result.confidence == 0.9

    def test_value_to_none_regressed(self) -> None:
        prev = _record(last_output="result")
        curr = _record(last_output=None)
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "regressed"

    def test_more_removals_than_additions(self) -> None:
        prev = _record(last_output={"keep": 1, "a": 2, "b": 3})
        curr = _record(last_output={"keep": 1, "c": 4})
        # 2 removed (a, b), 1 added (c) → net negative → regressed
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "regressed"

    def test_metadata_fields_removed(self) -> None:
        prev = _record(last_output={"x": 1}, metadata={"a": 1, "b": 2})
        curr = _record(last_output={"x": 1}, metadata={"a": 1})
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "regressed"
        assert "metadata: 1 field(s) removed" in result.reasons

    def test_more_side_effects(self) -> None:
        """More side effects between cycles → regressed."""
        prev = _record(last_output={"x": 1}, signals=[])
        curr = _record(
            last_output={"x": 1},
            signals=[_signal(BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT)],
        )
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "regressed"
        assert any("side effects" in r for r in result.reasons)


# =============================================================================
# Determinism
# =============================================================================


class TestDetectProgressDeterminism:
    """Tests for deterministic output."""

    def test_same_inputs_same_output(self) -> None:
        prev = _record(last_output={"x": 1, "y": 2})
        curr = _record(last_output={"x": 1, "y": 2, "z": 3})
        r1 = detect_progress(prev, curr)
        r2 = detect_progress(prev, curr)
        assert r1 is not None and r2 is not None
        assert r1.status == r2.status
        assert r1.confidence == r2.confidence
        assert r1.reasons == r2.reasons

    def test_reasons_ordered_deterministically(self) -> None:
        """Reasons should be emitted in a deterministic order."""
        prev = _record(last_output={"a": 1}, metadata={"x": 2})
        curr = _record(last_output={"a": 1, "b": 2}, metadata={"x": 2, "y": 3})
        r1 = detect_progress(prev, curr)
        r2 = detect_progress(prev, curr)
        assert r1 is not None and r2 is not None
        assert r1.reasons == r2.reasons
        # output reasons come before metadata reasons (sorted order)
        for reason in r1.reasons:
            # All reasons should be deterministic strings
            assert isinstance(reason, str)


# =============================================================================
# Non‑mutation
# =============================================================================


class TestDetectProgressNonMutation:
    """Tests that detect_progress does not mutate inputs."""

    def test_does_not_mutate_previous_last_output(self) -> None:
        prev_output = {"x": 1, "y": 2}
        prev = _record(last_output=prev_output)
        curr = _record(last_output={"x": 1, "y": 2, "z": 3})
        original = dict(prev_output)
        detect_progress(prev, curr)
        assert prev.last_output == original

    def test_does_not_mutate_current_last_output(self) -> None:
        curr_output = {"x": 1, "y": 2, "z": 3}
        prev = _record(last_output={"x": 1, "y": 2})
        curr = _record(last_output=curr_output)
        original = dict(curr_output)
        detect_progress(prev, curr)
        assert curr.last_output == original

    def test_does_not_mutate_metadata(self) -> None:
        prev_meta = {"v": 1.0}
        curr_meta = {"v": 2.0}
        prev = _record(last_output={"x": 1}, metadata=prev_meta)
        curr = _record(last_output={"x": 1}, metadata=curr_meta)
        detect_progress(prev, curr)
        assert prev.metadata == {"v": 1.0}
        assert curr.metadata == {"v": 2.0}

    def test_does_not_mutate_signals(self) -> None:
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        prev = _record(last_output={"x": 1}, signals=[])
        curr = _record(last_output={"x": 1}, signals=[sig])
        detect_progress(prev, curr)
        assert prev.behavioural_signals == []
        assert curr.behavioural_signals == [sig]


# =============================================================================
# JSON‑safe output
# =============================================================================


class TestDetectProgressJsonSafe:
    """Tests that ProgressSignal output is JSON‑serializable."""

    def test_output_json_serializable(self) -> None:
        prev = _record(last_output={"x": 1})
        curr = _record(last_output={"x": 1, "y": 2})
        result = detect_progress(prev, curr)
        assert result is not None
        data = {
            "status": result.status,
            "confidence": result.confidence,
            "reasons": result.reasons,
        }
        serialized = json.dumps(data)
        assert isinstance(serialized, str)

    def test_none_result_json_serializable(self) -> None:
        result = detect_progress(None, _record())
        assert result is None
        serialized = json.dumps(None)
        assert serialized == "null"


# =============================================================================
# Multiple reasons
# =============================================================================


class TestDetectProgressMultipleReasons:
    """Tests for multiple concurrent reasons."""

    def test_output_and_metadata_both_added(self) -> None:
        prev = _record(last_output={"x": 1}, metadata={"v": 1})
        curr = _record(last_output={"x": 1, "y": 2}, metadata={"v": 1, "w": 2})
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "steady"
        assert len(result.reasons) == 2
        assert "output: 1 field(s) added" in result.reasons
        assert "metadata: 1 field(s) added" in result.reasons

    def test_output_changed_and_metadata_removed(self) -> None:
        prev = _record(
            last_output={"x": 1, "y": 2},
            metadata={"a": 1, "b": 2},
        )
        curr = _record(
            last_output={"x": 1, "y": 99},
            metadata={"a": 1},
        )
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "regressed"
        # Should have 2 reasons: output changed + metadata removed
        assert len(result.reasons) >= 2

    def test_side_effect_reason_included(self) -> None:
        prev = _record(last_output={"x": 1}, signals=[])
        curr = _record(
            last_output={"x": 1},
            signals=[
                _signal(BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT),
                _signal(BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT),
            ],
        )
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "regressed"
        assert any("2 new unexpected side effect" in r for r in result.reasons)


# =============================================================================
# Edge cases
# =============================================================================


class TestDetectProgressEdgeCases:
    """Edge case tests for detect_progress."""

    def test_simple_string_diff_changed(self) -> None:
        prev = _record(last_output="abc")
        curr = _record(last_output="xyz")
        result = detect_progress(prev, curr)
        assert result is not None
        # Simple values differ → treated as "changed" → no additions → regressed
        assert result.status == "regressed"

    def test_bool_diff(self) -> None:
        prev = _record(last_output=True)
        curr = _record(last_output=False)
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "regressed"

    def test_int_diff(self) -> None:
        prev = _record(last_output=0)
        curr = _record(last_output=5)
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "regressed"  # non-dict diff → "changed" = regressed

    def test_empty_dicts(self) -> None:
        prev = _record(last_output={})
        curr = _record(last_output={})
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "stalled"

    def test_nested_dict_identical(self) -> None:
        prev = _record(last_output={"a": {"b": 1}})
        curr = _record(last_output={"a": {"b": 1}})
        result = detect_progress(prev, curr)
        assert result is not None
        assert result.status == "stalled"

    def test_nested_dict_different(self) -> None:
        prev = _record(last_output={"a": {"b": 1}})
        curr = _record(last_output={"a": {"b": 2}})
        result = detect_progress(prev, curr)
        assert result is not None
        # "a" key exists in both, values differ → "changed"
        assert result.status == "regressed"
