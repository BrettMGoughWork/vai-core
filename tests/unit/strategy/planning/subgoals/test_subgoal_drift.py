"""
Phase 2.12.3 — Subgoal‑Level Drift tests
"""
from __future__ import annotations

import json

import pytest

from src.strategy.planning.subgoals.drift import (
    SubgoalDriftResult,
    apply_subgoal_repair,
    classify_subgoal_drift,
    decide_subgoal_drift_action,
    evaluate_subgoal_drift,
)
from src.strategy.planning.subgoals.reflection import _subgoal_to_safe_dict
from src.strategy.types.plan_segment import PlanSegment
from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_subgoal(
    subgoal_id: str = "sg.test",
    goal: str = "Test goal",
    context: dict | None = None,
    metadata: dict | None = None,
    parent_id: str | None = None,
    state: SubgoalLifecycleState = SubgoalLifecycleState.ACTIVE,
) -> Subgoal:
    """Create a minimal valid Subgoal for testing."""
    if context is None:
        context = {"key": "value"}
    if metadata is None:
        metadata = {}
    return Subgoal(
        subgoal_id=subgoal_id,
        goal=goal,
        context=context,
        metadata=metadata,
        parent_id=parent_id,
        state=state,
    )


def _make_segment(
    subgoal_id: str = "sg.test",
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
# SubgoalDriftResult dataclass
# ──────────────────────────────────────────────────────────────────────────────


class TestSubgoalDriftResult:
    """Tests for the SubgoalDriftResult frozen dataclass."""

    def test_construction(self):
        """SubgoalDriftResult constructs with all required fields."""
        r = SubgoalDriftResult(
            drift={"status": "no_drift", "severity": "minor"},
            action="none",
            repaired_subgoal={"subgoal_id": "sg.test", "goal": "Test"},
            requires_replan=False,
        )
        assert r.drift == {"status": "no_drift", "severity": "minor"}
        assert r.action == "none"
        assert r.requires_replan is False

    def test_is_frozen(self):
        """SubgoalDriftResult is immutable."""
        r = SubgoalDriftResult(
            drift={}, action="none", repaired_subgoal={}, requires_replan=False
        )
        with pytest.raises(Exception):
            r.action = "repair_subgoal"  # type: ignore[misc]

    def test_json_safe(self):
        """All SubgoalDriftResult fields are JSON‑serialisable."""
        r = SubgoalDriftResult(
            drift={
                "status": "drift_detected",
                "severity": "major",
                "categories": ["structural"],
                "confidence": 0.6,
                "streak": 1,
                "signal_count": 2,
            },
            action="repair_subgoal",
            repaired_subgoal={
                "subgoal_id": "sg.test",
                "goal": "Fixed",
                "context": {},
                "metadata": {},
                "parent_id": None,
                "state": "active",
            },
            requires_replan=False,
        )
        assert _is_json_safe(r.drift)
        assert _is_json_safe(r.repaired_subgoal)
        d = {
            "drift": r.drift,
            "action": r.action,
            "repaired_subgoal": r.repaired_subgoal,
            "requires_replan": r.requires_replan,
        }
        assert _is_json_safe(d)

    def test_replan_result_json_safe(self):
        """Replan result with requires_replan=True is JSON‑safe."""
        r = SubgoalDriftResult(
            drift={"status": "drift_detected", "severity": "catastrophic"},
            action="replan_subgoal",
            repaired_subgoal={"subgoal_id": "sg.test", "goal": "Test"},
            requires_replan=True,
        )
        d = {
            "drift": r.drift,
            "action": r.action,
            "repaired_subgoal": r.repaired_subgoal,
            "requires_replan": r.requires_replan,
        }
        assert _is_json_safe(d)

    def test_deterministic_equality(self):
        """Identical inputs produce equal SubgoalDriftResult instances."""
        r1 = SubgoalDriftResult(
            drift={"status": "no_drift"},
            action="none",
            repaired_subgoal={"subgoal_id": "sg.test"},
            requires_replan=False,
        )
        r2 = SubgoalDriftResult(
            drift={"status": "no_drift"},
            action="none",
            repaired_subgoal={"subgoal_id": "sg.test"},
            requires_replan=False,
        )
        assert r1 == r2
        assert hash(r1) == hash(r2)


# ──────────────────────────────────────────────────────────────────────────────
# classify_subgoal_drift
# ──────────────────────────────────────────────────────────────────────────────


class TestClassifySubgoalDrift:
    """Tests for classify_subgoal_drift — reuses the reflection classifier."""

    def test_no_drift_on_valid_subgoal(self):
        """Valid subgoal produces no_drift classification."""
        sg = _make_subgoal()
        segs = [_make_segment(subgoal_id="sg.test")]
        result = classify_subgoal_drift(sg, segs)
        assert result["status"] == "no_drift"
        assert result["signal_count"] == 0

    def test_non_dict_context_produces_drift(self):
        """Subgoal with non-dict context triggers drift detection."""
        sg = _make_subgoal(context="not_a_dict")  # type: ignore[arg-type]
        result = classify_subgoal_drift(sg)
        assert result["status"] == "drift_detected"
        assert result["signal_count"] >= 1

    def test_empty_goal_produces_drift(self):
        """Subgoal with empty goal triggers drift detection."""
        sg = _make_subgoal(goal="")
        result = classify_subgoal_drift(sg)
        assert result["status"] == "drift_detected"
        assert result["signal_count"] >= 1

    def test_associated_segments_with_empty_steps_produce_drift(self):
        """Associated segments with empty steps trigger segment-level drift."""
        sg = _make_subgoal(subgoal_id="sg.test")
        segs = [_make_segment(subgoal_id="sg.test", steps=[])]
        result = classify_subgoal_drift(sg, segs)
        assert result["status"] == "drift_detected"
        assert result["signal_count"] >= 1

    def test_empty_segments_produce_drift(self):
        """Segments with empty steps trigger drift."""
        sg = _make_subgoal(subgoal_id="sg.test")
        segs = [_make_segment(subgoal_id="sg.test", steps=[])]
        result = classify_subgoal_drift(sg, segs)
        assert result["status"] == "drift_detected"

    def test_returns_expected_keys(self):
        """Classification dict has all required keys."""
        sg = _make_subgoal()
        result = classify_subgoal_drift(sg)
        for key in ("status", "severity", "categories", "confidence", "streak", "signal_count"):
            assert key in result, f"Missing key: {key}"

    def test_deterministic(self):
        """Same subgoal always produces the same classification."""
        sg = _make_subgoal(context={})
        r1 = classify_subgoal_drift(sg)
        r2 = classify_subgoal_drift(sg)
        assert r1 == r2

    def test_json_safe(self):
        """Classification dict is JSON‑safe."""
        sg = _make_subgoal()
        result = classify_subgoal_drift(sg)
        assert _is_json_safe(result)


# ──────────────────────────────────────────────────────────────────────────────
# decide_subgoal_drift_action
# ──────────────────────────────────────────────────────────────────────────────


class TestDecideSubgoalDriftAction:
    """Tests for decide_subgoal_drift_action."""

    def test_no_drift_returns_none(self):
        """No drift → action 'none'."""
        drift = {"status": "no_drift", "severity": "minor"}
        assert decide_subgoal_drift_action(drift) == "none"

    def test_minor_drift_returns_repair(self):
        """Minor drift → action 'repair_subgoal'."""
        drift = {"status": "drift_detected", "severity": "minor"}
        assert decide_subgoal_drift_action(drift) == "repair_subgoal"

    def test_major_drift_returns_repair(self):
        """Major drift → action 'repair_subgoal'."""
        drift = {"status": "drift_detected", "severity": "major"}
        assert decide_subgoal_drift_action(drift) == "repair_subgoal"

    def test_catastrophic_drift_returns_replan(self):
        """Catastrophic drift → action 'replan_subgoal'."""
        drift = {"status": "drift_detected", "severity": "catastrophic"}
        assert decide_subgoal_drift_action(drift) == "replan_subgoal"

    def test_missing_severity_defaults_to_repair(self):
        """Missing severity key defaults to repair (not catastrophic)."""
        drift = {"status": "drift_detected"}
        assert decide_subgoal_drift_action(drift) == "repair_subgoal"

    def test_missing_status_defaults_to_repair(self):
        """Missing status key defaults to repair."""
        drift: dict = {}
        assert decide_subgoal_drift_action(drift) == "repair_subgoal"

    def test_deterministic(self):
        """Same drift dict always produces the same action."""
        drift = {"status": "drift_detected", "severity": "major"}
        a1 = decide_subgoal_drift_action(drift)
        a2 = decide_subgoal_drift_action(drift)
        assert a1 == a2


# ──────────────────────────────────────────────────────────────────────────────
# apply_subgoal_repair
# ──────────────────────────────────────────────────────────────────────────────


class TestApplySubgoalRepair:
    """Tests for apply_subgoal_repair — reuses repair_subgoal from repair library."""

    def test_no_drift_returns_original(self):
        """No drift → original subgoal returned unchanged as safe dict."""
        sg = _make_subgoal(subgoal_id="original")
        drift = {"status": "no_drift"}
        result = apply_subgoal_repair(sg, drift)
        assert result["subgoal_id"] == "original"
        assert result["goal"] == "Test goal"

    def test_repair_fills_missing_goal(self):
        """Subgoal with empty goal gets repaired."""
        sg = _make_subgoal(goal="")
        drift = {"status": "drift_detected", "severity": "minor"}
        result = apply_subgoal_repair(sg, drift)
        assert result["goal"], "goal should be filled by repair"
        assert isinstance(result["goal"], str)

    def test_result_is_json_safe(self):
        """Repair result dict is JSON‑safe."""
        sg = _make_subgoal()
        drift = {"status": "no_drift"}
        result = apply_subgoal_repair(sg, drift)
        assert _is_json_safe(result)

    def test_result_is_dict(self):
        """apply_subgoal_repair always returns a dict."""
        sg = _make_subgoal()
        drift = {"status": "drift_detected", "severity": "minor"}
        result = apply_subgoal_repair(sg, drift)
        assert isinstance(result, dict)

    def test_preserves_valid_fields(self):
        """Repair preserves fields that were already valid."""
        sg = _make_subgoal(subgoal_id="keep.me", goal="Keep me")
        drift = {"status": "drift_detected", "severity": "minor"}
        result = apply_subgoal_repair(sg, drift)
        assert result["subgoal_id"] == "keep.me"
        assert result["goal"] == "Keep me"

    def test_deterministic(self):
        """Same inputs produce identical repair results."""
        sg = _make_subgoal(goal="")
        drift = {"status": "drift_detected", "severity": "minor"}
        r1 = apply_subgoal_repair(sg, drift)
        r2 = apply_subgoal_repair(sg, drift)
        assert r1 == r2


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_subgoal_drift (orchestrator)
# ──────────────────────────────────────────────────────────────────────────────


class TestEvaluateSubgoalDrift:
    """Tests for evaluate_subgoal_drift — the full pipeline orchestrator."""

    def test_valid_subgoal_returns_none_action(self):
        """Valid subgoal → no drift → action 'none'."""
        sg = _make_subgoal()
        segs = [_make_segment(subgoal_id="sg.test")]
        result = evaluate_subgoal_drift(sg, segs)
        assert result.action == "none"
        assert result.requires_replan is False
        assert result.repaired_subgoal["subgoal_id"] == "sg.test"

    def test_minor_drift_returns_repair_action(self):
        """Non-dict context → minor drift → action 'repair_subgoal'."""
        sg = _make_subgoal(context="bad_type")  # type: ignore[arg-type]
        result = evaluate_subgoal_drift(sg)
        assert result.action == "repair_subgoal"
        assert result.requires_replan is False

    def test_severely_broken_subgoal_triggers_repair(self):
        """Deeply broken subgoal → drift detected → action is repair or replan."""
        sg = Subgoal(
            subgoal_id="",
            goal="",
            context={},
            metadata={},
            parent_id=None,
            state=SubgoalLifecycleState.ACTIVE,
        )
        result = evaluate_subgoal_drift(sg)
        assert result.action in ("repair_subgoal", "replan_subgoal")
        assert result.action != "none"

    def test_catastrophic_decision_via_direct_call(self):
        """Catastrophic severity → decide_subgoal_drift_action returns 'replan_subgoal'."""
        drift = {"status": "drift_detected", "severity": "catastrophic"}
        assert decide_subgoal_drift_action(drift) == "replan_subgoal"

    def test_replan_flag_is_false_for_repair(self):
        """requires_replan is False when action is 'repair_subgoal'."""
        sg = _make_subgoal(goal="")
        result = evaluate_subgoal_drift(sg)
        assert result.action == "repair_subgoal"
        assert result.requires_replan is False

    def test_replan_flag_is_true_for_replan(self):
        """requires_replan is True when action is 'replan_subgoal'."""
        sg = Subgoal(
            subgoal_id="",
            goal="",
            context={},
            metadata={},
            parent_id=None,
            state=SubgoalLifecycleState.ACTIVE,
        )
        result = evaluate_subgoal_drift(sg)
        if result.action == "replan_subgoal":
            assert result.requires_replan is True

    def test_deterministic(self):
        """Same subgoal always produces identical drift results."""
        sg = _make_subgoal(context={})
        r1 = evaluate_subgoal_drift(sg)
        r2 = evaluate_subgoal_drift(sg)
        assert r1 == r2
        assert hash(r1) == hash(r2)

    def test_json_safe(self):
        """The full SubgoalDriftResult is JSON‑safe."""
        sg = _make_subgoal()
        segs = [_make_segment(subgoal_id="sg.test")]
        result = evaluate_subgoal_drift(sg, segs)
        d = {
            "drift": result.drift,
            "action": result.action,
            "repaired_subgoal": result.repaired_subgoal,
            "requires_replan": result.requires_replan,
        }
        assert _is_json_safe(d)

    def test_result_is_frozen(self):
        """SubgoalDriftResult is immutable."""
        result = evaluate_subgoal_drift(_make_subgoal())
        with pytest.raises(Exception):
            result.action = "changed"  # type: ignore[misc]

    def test_repaired_subgoal_is_preserved(self):
        """Repair action returns repaired subgoal with filled fields."""
        sg = _make_subgoal(context={})
        result = evaluate_subgoal_drift(sg)
        if result.action == "repair_subgoal":
            assert isinstance(result.repaired_subgoal, dict)
            assert "subgoal_id" in result.repaired_subgoal

    def test_replan_preserves_original_subgoal(self):
        """Replan action returns the original subgoal dict (placeholder)."""
        sg = _make_subgoal(subgoal_id="original_id")
        result = evaluate_subgoal_drift(sg)
        if result.action == "replan_subgoal":
            assert result.repaired_subgoal["subgoal_id"] == "original_id"

    def test_empty_goal_triggers_repair_not_replan(self):
        """Empty goal alone should trigger repair, not replan."""
        sg = _make_subgoal(subgoal_id="valid.id", goal="")
        result = evaluate_subgoal_drift(sg)
        assert result.action == "repair_subgoal"
        assert result.requires_replan is False


# ──────────────────────────────────────────────────────────────────────────────
# Integration: full pipeline ordering
# ──────────────────────────────────────────────────────────────────────────────


class TestPipelineOrdering:
    """Verify the pipeline runs in the correct deterministic order."""

    def test_classify_called_first(self):
        """Drift in result comes from classifier."""
        sg = _make_subgoal(context="bad")  # type: ignore[arg-type]
        result = evaluate_subgoal_drift(sg)
        assert "status" in result.drift
        assert "severity" in result.drift
        assert result.drift["status"] == "drift_detected"

    def test_action_matches_drift_severity(self):
        """Action is consistent with drift severity."""
        sg = _make_subgoal(context="bad")  # type: ignore[arg-type]
        result = evaluate_subgoal_drift(sg)
        if result.drift["severity"] == "catastrophic":
            assert result.action == "replan_subgoal"
            assert result.requires_replan is True
        else:
            assert result.action in ("none", "repair_subgoal")
            assert result.requires_replan is False

    def test_all_outputs_json_safe(self):
        """Every dict in the result is JSON‑serialisable."""
        sg = _make_subgoal(context={})
        result = evaluate_subgoal_drift(sg)
        assert _is_json_safe(result.drift)
        assert _is_json_safe(result.repaired_subgoal)
        assert _is_json_safe({
            "drift": result.drift,
            "action": result.action,
            "repaired_subgoal": result.repaired_subgoal,
            "requires_replan": result.requires_replan,
        })

    def test_no_segments_no_drift(self):
        """Valid subgoal without segments → no drift."""
        sg = _make_subgoal()
        result = evaluate_subgoal_drift(sg)
        assert result.drift["status"] == "no_drift"


# ──────────────────────────────────────────────────────────────────────────────
# Purity: no side effects
# ──────────────────────────────────────────────────────────────────────────────


class TestPurity:
    """Verify all functions are pure — no mutation of inputs."""

    def test_classify_does_not_mutate_subgoal(self):
        """classify_subgoal_drift does not modify the subgoal."""
        sg = _make_subgoal(goal="before")
        _ = classify_subgoal_drift(sg)
        assert sg.goal == "before"

    def test_apply_repair_does_not_mutate_subgoal(self):
        """apply_subgoal_repair does not modify the subgoal."""
        sg = _make_subgoal(goal="")
        _ = apply_subgoal_repair(sg, {"status": "drift_detected", "severity": "minor"})
        assert sg.goal == ""

    def test_evaluate_does_not_mutate_subgoal(self):
        """evaluate_subgoal_drift does not modify the subgoal."""
        sg = _make_subgoal(goal="before")
        _ = evaluate_subgoal_drift(sg)
        assert sg.goal == "before"

    def test_safe_dict_unchanged_between_calls(self):
        """_subgoal_to_safe_dict returns same result for unchanged subgoal."""
        sg = _make_subgoal(subgoal_id="s")
        before = _subgoal_to_safe_dict(sg)
        after = _subgoal_to_safe_dict(sg)
        assert before == after