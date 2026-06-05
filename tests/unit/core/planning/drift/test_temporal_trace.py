"""
Tests for Phase 2.7.5 — Temporal Trace.

Covers:
  - TemporalTrace dataclass validation
  - build_temporal_trace() pure function
  - progress_deltas computed correctly
  - stall_reasons extracted correctly
  - oscillation_markers extracted correctly
  - No mutation of inputs
  - Deterministic output
  - JSON safety
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from src.core.planning.drift.behavioural_signal_types import (
    BehaviouralSignal,
    BehaviouralSignalType,
)
from src.core.planning.drift.segment_trace_types import TemporalTrace
from src.core.planning.drift.temporal_signal_types import (
    ProgressSignal,
    TemporalDriftClassification,
    TemporalDriftSignal,
    TemporalRepairPlan,
)
from src.core.planning.drift.temporal_trace import (
    _extract_oscillation_markers,
    _extract_stall_reasons,
    _structural_diff,
    build_temporal_trace,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _make_record(
    *,
    last_output: Any = None,
    metadata: Dict[str, Any] | None = None,
    behavioural_signals: List[BehaviouralSignal] | None = None,
) -> "SegmentMemoryRecord":
    """Build a minimal SegmentMemoryRecord for testing."""
    from src.core.memory.segment_memory_types import SegmentMemoryRecord

    return SegmentMemoryRecord(
        segment_id="test-seg",
        parent_id=None,
        subgoal_id="test-subgoal",
        state=None,
        content=[],
        created_at="2025-01-01T00:00:00Z",
        context={},
        metadata=metadata or {},
        last_output=last_output,
        behavioural_signals=behavioural_signals or [],
    )


def _make_progress_signal(
    status: str = "steady",
    confidence: float = 0.7,
    reasons: List[str] | None = None,
) -> ProgressSignal:
    return ProgressSignal(
        status=status,  # type: ignore[arg-type]
        confidence=confidence,
        reasons=reasons or [],
    )


def _make_temporal_signal(
    signal_type: str,
    confidence: float = 0.7,
    details: Dict[str, Any] | None = None,
) -> TemporalDriftSignal:
    return TemporalDriftSignal(
        type=signal_type,  # type: ignore[arg-type]
        confidence=confidence,
        details=details or {},
    )


def _make_classification(
    status: str = "no_drift",
    categories: List[str] | None = None,
    confidence: float = 0.0,
    reasons: List[TemporalDriftSignal] | None = None,
    streak: int = 0,
) -> TemporalDriftClassification:
    return TemporalDriftClassification(
        status=status,  # type: ignore[arg-type]
        categories=categories or [],
        confidence=confidence,
        reasons=reasons or [],
        streak=streak,
    )


def _make_repair(
    needs_repair: bool = False,
    repair_actions: List[str] | None = None,
    confidence: float = 0.0,
    categories: List[str] | None = None,
    streak: int = 0,
) -> TemporalRepairPlan:
    return TemporalRepairPlan(
        needs_repair=needs_repair,
        repair_actions=repair_actions or [],
        confidence=confidence,
        categories=categories or [],
        streak=streak,
    )


# ============================================================================
# TemporalTrace dataclass
# ============================================================================


class TestTemporalTrace:
    """Tests for the TemporalTrace frozen dataclass."""

    def test_empty_trace_construction(self) -> None:
        trace = TemporalTrace(
            progress_deltas={"output_delta": {}, "metadata_delta": {}},
            stall_reasons=[],
            oscillation_markers=[],
        )
        assert trace.progress_deltas == {"output_delta": {}, "metadata_delta": {}}
        assert trace.stall_reasons == []
        assert trace.oscillation_markers == []

    def test_full_trace_construction(self) -> None:
        trace = TemporalTrace(
            progress_deltas={
                "output_delta": {"previous": 1, "current": 2},
                "metadata_delta": {"added": {}, "removed": {}, "changed": {}},
                "side_effects_delta": {"previous_count": 0, "current_count": 1, "net_change": 1},
            },
            stall_reasons=["progress stalled: no change"],
            oscillation_markers=["oscillation detected: A→B→A"],
        )
        assert "output_delta" in trace.progress_deltas
        assert "metadata_delta" in trace.progress_deltas
        assert "side_effects_delta" in trace.progress_deltas
        assert trace.stall_reasons == ["progress stalled: no change"]
        assert trace.oscillation_markers == ["oscillation detected: A→B→A"]

    def test_frozen(self) -> None:
        trace = TemporalTrace(
            progress_deltas={},
            stall_reasons=[],
            oscillation_markers=[],
        )
        with pytest.raises(Exception):
            trace.stall_reasons = ["mutated"]  # type: ignore[misc]

    def test_stall_reasons_defensive_copy(self) -> None:
        reasons = ["a", "b"]
        trace = TemporalTrace(
            progress_deltas={},
            stall_reasons=reasons,
            oscillation_markers=[],
        )
        reasons.append("c")
        assert trace.stall_reasons == ["a", "b"]

    def test_oscillation_markers_defensive_copy(self) -> None:
        markers = ["a", "b"]
        trace = TemporalTrace(
            progress_deltas={},
            stall_reasons=[],
            oscillation_markers=markers,
        )
        markers.append("c")
        assert trace.oscillation_markers == ["a", "b"]


# ============================================================================
# _structural_diff
# ============================================================================


class TestStructuralDiff:
    """Tests for the private _structural_diff helper."""

    def test_both_none(self) -> None:
        result = _structural_diff(None, None)
        assert result == {"previous": None, "current": None}

    def test_scalar_change(self) -> None:
        result = _structural_diff(1, 2)
        assert result == {"previous": 1, "current": 2}

    def test_dict_identical(self) -> None:
        result = _structural_diff({"a": 1}, {"a": 1})
        assert result == {"added": {}, "removed": {}, "changed": {}}

    def test_dict_added_key(self) -> None:
        result = _structural_diff({"a": 1}, {"a": 1, "b": 2})
        assert result == {"added": {"b": 2}, "removed": {}, "changed": {}}

    def test_dict_removed_key(self) -> None:
        result = _structural_diff({"a": 1, "b": 2}, {"a": 1})
        assert result == {"added": {}, "removed": {"b": 2}, "changed": {}}

    def test_dict_changed_key(self) -> None:
        result = _structural_diff({"a": 1}, {"a": 99})
        assert result == {"added": {}, "removed": {}, "changed": {"a": {"old": 1, "new": 99}}}


# ============================================================================
# _extract_stall_reasons
# ============================================================================


class TestExtractStallReasons:
    """Tests for stall reason extraction."""

    def test_no_stall_no_reasons(self) -> None:
        ps = _make_progress_signal(status="steady")
        reasons = _extract_stall_reasons(ps, [])
        assert reasons == []

    def test_progress_stalled_includes_reasons(self) -> None:
        ps = _make_progress_signal(status="stalled", reasons=["no meaningful change"])
        reasons = _extract_stall_reasons(ps, [])
        assert reasons == ["progress stalled: no meaningful change"]

    def test_no_progress_signal_includes_details(self) -> None:
        signal = _make_temporal_signal(
            "no_progress", details={"summary": "identical output detected"}
        )
        reasons = _extract_stall_reasons(None, [signal])
        assert reasons == ["temporal drift: identical output detected"]

    def test_combined_stall_reasons_sorted(self) -> None:
        ps = _make_progress_signal(status="stalled", reasons=["b reason"])
        signal = _make_temporal_signal(
            "no_progress", details={"summary": "a detail"}
        )
        reasons = _extract_stall_reasons(ps, [signal])
        # Sorted deterministically
        assert reasons == [
            "progress stalled: b reason",
            "temporal drift: a detail",
        ]

    def test_null_progress_signal(self) -> None:
        reasons = _extract_stall_reasons(None, [])
        assert reasons == []

    def test_only_other_signal_types_ignored(self) -> None:
        signal = _make_temporal_signal("repetition")
        reasons = _extract_stall_reasons(None, [signal])
        assert reasons == []


# ============================================================================
# _extract_oscillation_markers
# ============================================================================


class TestExtractOscillationMarkers:
    """Tests for oscillation marker extraction."""

    def test_no_oscillation_no_markers(self) -> None:
        markers = _extract_oscillation_markers([])
        assert markers == []

    def test_oscillation_signal_included(self) -> None:
        signal = _make_temporal_signal(
            "oscillation", details={"pattern": "A→B→A"}
        )
        markers = _extract_oscillation_markers([signal])
        assert markers == ["oscillation detected: A→B→A"]

    def test_multiple_oscillations_sorted(self) -> None:
        s1 = _make_temporal_signal("oscillation", details={"pattern": "z pattern"})
        s2 = _make_temporal_signal("oscillation", details={"pattern": "a pattern"})
        markers = _extract_oscillation_markers([s1, s2])
        assert markers == [
            "oscillation detected: a pattern",
            "oscillation detected: z pattern",
        ]

    def test_mixed_signals_only_oscillation(self) -> None:
        signals = [
            _make_temporal_signal("no_progress"),
            _make_temporal_signal("oscillation", details={"pattern": "osc"}),
            _make_temporal_signal("repetition"),
        ]
        markers = _extract_oscillation_markers(signals)
        assert markers == ["oscillation detected: osc"]


# ============================================================================
# build_temporal_trace — core logic
# ============================================================================


class TestBuildTemporalTrace:
    """Tests for the build_temporal_trace() pure function."""

    # ── progress_deltas ─────────────────────────────────────────────────

    def test_progress_deltas_with_no_previous(self) -> None:
        curr = _make_record(last_output={"x": 1}, metadata={"m": 1})
        trace = build_temporal_trace(
            previous_record=None,
            current_record=curr,
            progress_signal=None,
            temporal_signals=[],
            temporal_classification=_make_classification(),
            temporal_repair=_make_repair(),
        )
        assert "output_delta" in trace.progress_deltas
        assert trace.progress_deltas["output_delta"] == {
            "previous": None, "current": {"x": 1}
        }
        # side_effects_delta absent when no previous record
        assert "side_effects_delta" not in trace.progress_deltas

    def test_progress_deltas_with_previous(self) -> None:
        prev = _make_record(last_output={"a": 1}, metadata={"m": 1})
        curr = _make_record(last_output={"a": 1, "b": 2}, metadata={"m": 1})
        trace = build_temporal_trace(
            previous_record=prev,
            current_record=curr,
            progress_signal=None,
            temporal_signals=[],
            temporal_classification=_make_classification(),
            temporal_repair=_make_repair(),
        )
        assert trace.progress_deltas["output_delta"] == {
            "added": {"b": 2}, "removed": {}, "changed": {},
        }
        assert trace.progress_deltas["metadata_delta"] == {
            "added": {}, "removed": {}, "changed": {},
        }
        assert "side_effects_delta" in trace.progress_deltas
        assert trace.progress_deltas["side_effects_delta"]["net_change"] == 0

    def test_side_effects_delta_tracks_changes(self) -> None:
        se_signal = BehaviouralSignal(
            signal_type=BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT,
            segment_id="test-seg",
            subgoal_id="test-subgoal",
            details={"side_effect": "file_write"},
            timestamp="2025-01-01T00:00:00Z",
        )
        prev = _make_record(behavioural_signals=[])
        curr = _make_record(behavioural_signals=[se_signal])
        trace = build_temporal_trace(
            previous_record=prev,
            current_record=curr,
            progress_signal=None,
            temporal_signals=[],
            temporal_classification=_make_classification(),
            temporal_repair=_make_repair(),
        )
        se = trace.progress_deltas["side_effects_delta"]
        assert se["previous_count"] == 0
        assert se["current_count"] == 1
        assert se["net_change"] == 1

    # ── stall reasons ───────────────────────────────────────────────────

    def test_stall_reasons_from_stalled_progress(self) -> None:
        ps = _make_progress_signal(status="stalled", reasons=["no diff"])
        trace = build_temporal_trace(
            previous_record=_make_record(),
            current_record=_make_record(),
            progress_signal=ps,
            temporal_signals=[],
            temporal_classification=_make_classification(),
            temporal_repair=_make_repair(),
        )
        assert trace.stall_reasons == ["progress stalled: no diff"]

    def test_stall_reasons_from_no_progress_signal(self) -> None:
        s = _make_temporal_signal(
            "no_progress", details={"summary": "output unchanged"}
        )
        trace = build_temporal_trace(
            previous_record=_make_record(),
            current_record=_make_record(),
            progress_signal=None,
            temporal_signals=[s],
            temporal_classification=_make_classification(),
            temporal_repair=_make_repair(),
        )
        assert trace.stall_reasons == ["temporal drift: output unchanged"]

    # ── oscillation markers ─────────────────────────────────────────────

    def test_oscillation_markers(self) -> None:
        s = _make_temporal_signal(
            "oscillation", details={"pattern": "A→B→A"}
        )
        trace = build_temporal_trace(
            previous_record=_make_record(),
            current_record=_make_record(),
            progress_signal=None,
            temporal_signals=[s],
            temporal_classification=_make_classification(),
            temporal_repair=_make_repair(),
        )
        assert trace.oscillation_markers == ["oscillation detected: A→B→A"]

    # ── determinism ─────────────────────────────────────────────────────

    def test_deterministic_output(self) -> None:
        prev = _make_record(last_output={"x": 1})
        curr = _make_record(last_output={"x": 2})
        ps = _make_progress_signal(status="steady", reasons=["changed"])
        signals = [
            _make_temporal_signal("repetition", details={"hash": "abc"}),
        ]

        t1 = build_temporal_trace(
            previous_record=prev,
            current_record=curr,
            progress_signal=ps,
            temporal_signals=signals,
            temporal_classification=_make_classification(status="temporal_drift", confidence=0.7),
            temporal_repair=_make_repair(needs_repair=True),
        )
        t2 = build_temporal_trace(
            previous_record=prev,
            current_record=curr,
            progress_signal=ps,
            temporal_signals=signals,
            temporal_classification=_make_classification(status="temporal_drift", confidence=0.7),
            temporal_repair=_make_repair(needs_repair=True),
        )
        assert t1.progress_deltas == t2.progress_deltas
        assert t1.stall_reasons == t2.stall_reasons
        assert t1.oscillation_markers == t2.oscillation_markers

    # ── non-mutation invariants ─────────────────────────────────────────

    def test_does_not_mutate_records(self) -> None:
        prev = _make_record(last_output={"a": 1})
        curr = _make_record(last_output={"a": 2})
        build_temporal_trace(
            previous_record=prev,
            current_record=curr,
            progress_signal=None,
            temporal_signals=[],
            temporal_classification=_make_classification(),
            temporal_repair=_make_repair(),
        )
        assert prev.last_output == {"a": 1}
        assert curr.last_output == {"a": 2}

    def test_does_not_mutate_progress_signal(self) -> None:
        ps = _make_progress_signal(status="stalled", reasons=["r"])
        build_temporal_trace(
            previous_record=_make_record(),
            current_record=_make_record(),
            progress_signal=ps,
            temporal_signals=[],
            temporal_classification=_make_classification(),
            temporal_repair=_make_repair(),
        )
        assert ps.status == "stalled"
        assert ps.reasons == ["r"]

    def test_does_not_mutate_temporal_signals(self) -> None:
        s = _make_temporal_signal("oscillation", details={"pattern": "p"})
        signals = [s]
        build_temporal_trace(
            previous_record=_make_record(),
            current_record=_make_record(),
            progress_signal=None,
            temporal_signals=signals,
            temporal_classification=_make_classification(),
            temporal_repair=_make_repair(),
        )
        assert s.type == "oscillation"
        assert s.details == {"pattern": "p"}

    # ── JSON safety ─────────────────────────────────────────────────────

    def test_result_is_json_safe(self) -> None:
        trace = build_temporal_trace(
            previous_record=_make_record(last_output={"x": 1}),
            current_record=_make_record(last_output={"x": 2, "y": 3}),
            progress_signal=_make_progress_signal(status="steady", reasons=["output: 1 field(s) added"]),
            temporal_signals=[],
            temporal_classification=_make_classification(),
            temporal_repair=_make_repair(),
        )
        dumped = json.dumps({
            "progress_deltas": trace.progress_deltas,
            "stall_reasons": trace.stall_reasons,
            "oscillation_markers": trace.oscillation_markers,
        })
        assert isinstance(dumped, str)
        # Round-trip
        loaded = json.loads(dumped)
        assert loaded["progress_deltas"] == trace.progress_deltas
        assert loaded["stall_reasons"] == trace.stall_reasons
        assert loaded["oscillation_markers"] == trace.oscillation_markers
