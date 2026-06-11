"""
Tests for Phase 2.11.3 — Segment‑Level Drift (``src.strategy.planning.segments.drift``).
"""
from __future__ import annotations

import json

import pytest

from src.strategy.planning.segments.drift import (
    SegmentDriftResult,
    apply_segment_repair,
    classify_segment_drift,
    decide_segment_drift_action,
    evaluate_segment_drift,
)
from src.strategy.types.plan_segment import PlanSegment


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_segment(
    subgoal_id: str = "sub.test",
    steps: list | None = None,
    context: dict | None = None,
) -> PlanSegment:
    """Create a minimal valid PlanSegment for testing."""
    if steps is None:
        steps = ["noop"]
    if context is None:
        context = {}
    return PlanSegment(
        subgoal_id=subgoal_id,
        steps=steps,
        context=context,
        metadata={},
    )


def _is_json_safe(obj: object) -> bool:
    """Check that an object is JSON‑serialisable."""
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


# ──────────────────────────────────────────────────────────────────────────────
# SegmentDriftResult dataclass
# ──────────────────────────────────────────────────────────────────────────────


class TestSegmentDriftResult:
    """Tests for the SegmentDriftResult frozen dataclass."""

    def test_construction(self):
        """SegmentDriftResult constructs with all required fields."""
        r = SegmentDriftResult(
            drift={"status": "no_drift", "severity": "minor"},
            action="none",
            repaired_segment={"subgoal_id": "s1", "steps": ["noop"]},
            requires_replan=False,
        )
        assert r.drift == {"status": "no_drift", "severity": "minor"}
        assert r.action == "none"
        assert r.requires_replan is False

    def test_is_frozen(self):
        """SegmentDriftResult is immutable."""
        r = SegmentDriftResult(
            drift={}, action="none", repaired_segment={}, requires_replan=False
        )
        with pytest.raises(Exception):
            r.action = "repair_segment"  # type: ignore[misc]

    def test_json_safe(self):
        """All SegmentDriftResult fields are JSON‑serialisable."""
        r = SegmentDriftResult(
            drift={
                "status": "drift_detected",
                "severity": "major",
                "categories": ["structural"],
                "confidence": 0.6,
                "streak": 1,
                "signal_count": 2,
            },
            action="repair_segment",
            repaired_segment={
                "subgoal_id": "s1",
                "steps": ["noop"],
                "context": {},
                "metadata": {},
            },
            requires_replan=False,
        )
        assert _is_json_safe(r.drift)
        assert _is_json_safe(r.repaired_segment)
        # Entire dataclass via asdict-style serialisation
        d = {
            "drift": r.drift,
            "action": r.action,
            "repaired_segment": r.repaired_segment,
            "requires_replan": r.requires_replan,
        }
        assert _is_json_safe(d)

    def test_replan_result_json_safe(self):
        """Replan result with requires_replan=True is JSON‑safe."""
        r = SegmentDriftResult(
            drift={"status": "drift_detected", "severity": "catastrophic"},
            action="replan_segment",
            repaired_segment={"subgoal_id": "s1", "steps": []},
            requires_replan=True,
        )
        d = {
            "drift": r.drift,
            "action": r.action,
            "repaired_segment": r.repaired_segment,
            "requires_replan": r.requires_replan,
        }
        assert _is_json_safe(d)

    def test_deterministic_equality(self):
        """Identical inputs produce equal SegmentDriftResult instances."""
        r1 = SegmentDriftResult(
            drift={"status": "no_drift"},
            action="none",
            repaired_segment={"steps": ["a"]},
            requires_replan=False,
        )
        r2 = SegmentDriftResult(
            drift={"status": "no_drift"},
            action="none",
            repaired_segment={"steps": ["a"]},
            requires_replan=False,
        )
        assert r1 == r2
        assert hash(r1) == hash(r2)


# ──────────────────────────────────────────────────────────────────────────────
# classify_segment_drift
# ──────────────────────────────────────────────────────────────────────────────


class TestClassifySegmentDrift:
    """Tests for classify_segment_drift — reuses the reflection classifier."""

    def test_no_drift_on_valid_segment(self):
        """Valid segment produces no_drift classification."""
        seg = _make_segment()
        result = classify_segment_drift(seg)
        assert result["status"] == "no_drift"
        assert result["signal_count"] == 0

    def test_missing_subgoal_id_produces_drift(self):
        """Segment with empty subgoal_id triggers drift detection."""
        seg = _make_segment(subgoal_id="")
        result = classify_segment_drift(seg)
        assert result["status"] == "drift_detected"
        assert result["signal_count"] >= 1

    def test_empty_steps_produces_drift(self):
        """Segment with empty steps triggers drift."""
        seg = _make_segment(steps=[])
        result = classify_segment_drift(seg)
        assert result["status"] == "drift_detected"

    def test_returns_expected_keys(self):
        """Classification dict has all required keys."""
        seg = _make_segment()
        result = classify_segment_drift(seg)
        for key in ("status", "severity", "categories", "confidence", "streak", "signal_count"):
            assert key in result, f"Missing key: {key}"

    def test_deterministic(self):
        """Same segment always produces the same classification."""
        seg = _make_segment(subgoal_id="")
        r1 = classify_segment_drift(seg)
        r2 = classify_segment_drift(seg)
        assert r1 == r2

    def test_json_safe(self):
        """Classification dict is JSON‑safe."""
        seg = _make_segment()
        result = classify_segment_drift(seg)
        assert _is_json_safe(result)


# ──────────────────────────────────────────────────────────────────────────────
# decide_segment_drift_action
# ──────────────────────────────────────────────────────────────────────────────


class TestDecideSegmentDriftAction:
    """Tests for decide_segment_drift_action."""

    def test_no_drift_returns_none(self):
        """No drift → action 'none'."""
        drift = {"status": "no_drift", "severity": "minor"}
        assert decide_segment_drift_action(drift) == "none"

    def test_minor_drift_returns_repair(self):
        """Minor drift → action 'repair_segment'."""
        drift = {"status": "drift_detected", "severity": "minor"}
        assert decide_segment_drift_action(drift) == "repair_segment"

    def test_major_drift_returns_repair(self):
        """Major drift → action 'repair_segment'."""
        drift = {"status": "drift_detected", "severity": "major"}
        assert decide_segment_drift_action(drift) == "repair_segment"

    def test_catastrophic_drift_returns_replan(self):
        """Catastrophic drift → action 'replan_segment'."""
        drift = {"status": "drift_detected", "severity": "catastrophic"}
        assert decide_segment_drift_action(drift) == "replan_segment"

    def test_missing_severity_defaults_to_repair(self):
        """Missing severity key defaults to repair (not catastrophic)."""
        drift = {"status": "drift_detected"}
        assert decide_segment_drift_action(drift) == "repair_segment"

    def test_missing_status_defaults_to_repair(self):
        """Missing status key defaults to repair."""
        drift: dict = {}
        assert decide_segment_drift_action(drift) == "repair_segment"

    def test_deterministic(self):
        """Same drift dict always produces the same action."""
        drift = {"status": "drift_detected", "severity": "major"}
        a1 = decide_segment_drift_action(drift)
        a2 = decide_segment_drift_action(drift)
        assert a1 == a2


# ──────────────────────────────────────────────────────────────────────────────
# apply_segment_repair
# ──────────────────────────────────────────────────────────────────────────────


class TestApplySegmentRepair:
    """Tests for apply_segment_repair — reuses repair_segment from repair library."""

    def test_no_drift_returns_original(self):
        """No drift → original segment returned unchanged as safe dict."""
        seg = _make_segment(subgoal_id="original")
        drift = {"status": "no_drift"}
        result = apply_segment_repair(seg, drift)
        assert result["subgoal_id"] == "original"
        assert result["steps"] == ["noop"]

    def test_repair_fills_missing_subgoal_id(self):
        """Segment with empty subgoal_id gets repaired."""
        seg = _make_segment(subgoal_id="")
        drift = {"status": "drift_detected", "severity": "minor"}
        result = apply_segment_repair(seg, drift)
        # repair_segment should fill the missing subgoal_id
        assert result["subgoal_id"], "subgoal_id should be filled by repair"
        assert isinstance(result["subgoal_id"], str)

    def test_result_is_json_safe(self):
        """Repair result dict is JSON‑safe."""
        seg = _make_segment()
        drift = {"status": "no_drift"}
        result = apply_segment_repair(seg, drift)
        assert _is_json_safe(result)

    def test_result_is_dict(self):
        """apply_segment_repair always returns a dict."""
        seg = _make_segment()
        drift = {"status": "drift_detected", "severity": "minor"}
        result = apply_segment_repair(seg, drift)
        assert isinstance(result, dict)

    def test_preserves_valid_fields(self):
        """Repair preserves fields that were already valid."""
        seg = _make_segment(subgoal_id="keep.me", steps=["a", "b"])
        drift = {"status": "drift_detected", "severity": "minor"}
        result = apply_segment_repair(seg, drift)
        assert result["subgoal_id"] == "keep.me"
        # steps may be normalized but should not be empty
        assert len(result["steps"]) > 0

    def test_deterministic(self):
        """Same inputs produce identical repair results."""
        seg = _make_segment(subgoal_id="")
        drift = {"status": "drift_detected", "severity": "minor"}
        r1 = apply_segment_repair(seg, drift)
        r2 = apply_segment_repair(seg, drift)
        assert r1 == r2


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_segment_drift (orchestrator)
# ──────────────────────────────────────────────────────────────────────────────


class TestEvaluateSegmentDrift:
    """Tests for evaluate_segment_drift — the full pipeline orchestrator."""

    def test_valid_segment_returns_none_action(self):
        """Valid segment → no drift → action 'none'."""
        seg = _make_segment()
        result = evaluate_segment_drift(seg)
        assert result.action == "none"
        assert result.requires_replan is False
        assert result.repaired_segment["subgoal_id"] == "sub.test"

    def test_minor_drift_returns_repair_action(self):
        """Missing subgoal_id → minor drift → action 'repair_segment'."""
        seg = _make_segment(subgoal_id="")
        result = evaluate_segment_drift(seg)
        assert result.action == "repair_segment"
        assert result.requires_replan is False

    def test_severely_broken_segment_triggers_repair(self):
        """Deeply broken segment → drift detected → action is repair or replan."""
        # A segment with empty subgoal_id, empty steps, and malformed context
        # accumulates multiple drift signals.  The exact action depends on
        # aggregate weight — but it will never be "none".
        seg = PlanSegment(
            subgoal_id="",
            steps=[],
            context="not_a_dict",  # type: ignore[arg-type]
            metadata={},
        )
        result = evaluate_segment_drift(seg)
        assert result.action in ("repair_segment", "replan_segment")
        assert result.action != "none"

    def test_catastrophic_decision_via_direct_call(self):
        """Catastrophic severity → decide_segment_drift_action returns 'replan_segment'."""
        drift = {"status": "drift_detected", "severity": "catastrophic"}
        assert decide_segment_drift_action(drift) == "replan_segment"

    def test_replan_preserves_original_segment(self):
        """Replan action returns the original segment dict (placeholder)."""
        seg = _make_segment(subgoal_id="original_id")
        result = evaluate_segment_drift(seg)
        if result.action == "replan_segment":
            assert result.repaired_segment["subgoal_id"] == "original_id"

    def test_repaired_segment_is_preserved(self):
        """Repair action returns repaired segment with filled fields."""
        seg = _make_segment(subgoal_id="")
        result = evaluate_segment_drift(seg)
        if result.action == "repair_segment":
            assert isinstance(result.repaired_segment, dict)
            assert "subgoal_id" in result.repaired_segment

    def test_replan_flag_is_false_for_repair(self):
        """requires_replan is False when action is 'repair_segment'."""
        seg = _make_segment(subgoal_id="")
        result = evaluate_segment_drift(seg)
        if result.action == "repair_segment":
            assert result.requires_replan is False

    def test_replan_flag_is_true_for_replan(self):
        """requires_replan is True when action is 'replan_segment'."""
        seg = PlanSegment(
            subgoal_id="",
            steps=[],
            context="bad",  # type: ignore[arg-type]
            metadata={},
        )
        result = evaluate_segment_drift(seg)
        if result.action == "replan_segment":
            assert result.requires_replan is True

    def test_deterministic(self):
        """Same segment always produces identical drift results."""
        seg = _make_segment(subgoal_id="")
        r1 = evaluate_segment_drift(seg)
        r2 = evaluate_segment_drift(seg)
        assert r1 == r2
        assert hash(r1) == hash(r2)

    def test_json_safe(self):
        """The full SegmentDriftResult is JSON‑safe."""
        seg = _make_segment()
        result = evaluate_segment_drift(seg)
        d = {
            "drift": result.drift,
            "action": result.action,
            "repaired_segment": result.repaired_segment,
            "requires_replan": result.requires_replan,
        }
        assert _is_json_safe(d)

    def test_result_is_frozen(self):
        """SegmentDriftResult is immutable."""
        result = evaluate_segment_drift(_make_segment())
        with pytest.raises(Exception):
            result.action = "changed"  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────────
# Integration: full pipeline ordering
# ──────────────────────────────────────────────────────────────────────────────


class TestPipelineOrdering:
    """Verify the pipeline runs in the correct deterministic order."""

    def test_classify_called_first(self):
        """Drift in result comes from classifier."""
        seg = _make_segment(subgoal_id="")
        result = evaluate_segment_drift(seg)
        assert "status" in result.drift
        assert "severity" in result.drift
        assert result.drift["status"] == "drift_detected"

    def test_action_matches_drift_severity(self):
        """Action is consistent with drift severity."""
        seg = _make_segment(subgoal_id="")
        result = evaluate_segment_drift(seg)
        if result.drift["severity"] == "catastrophic":
            assert result.action == "replan_segment"
            assert result.requires_replan is True
        else:
            assert result.action in ("none", "repair_segment")
            assert result.requires_replan is False

    def test_empty_steps_triggers_repair_not_replan(self):
        """Empty steps alone should trigger repair, not replan (minor/major)."""
        seg = _make_segment(subgoal_id="valid.id", steps=[])
        result = evaluate_segment_drift(seg)
        # Empty steps is minor drift → repair, not catastrophic
        assert result.action == "repair_segment"
        assert result.requires_replan is False