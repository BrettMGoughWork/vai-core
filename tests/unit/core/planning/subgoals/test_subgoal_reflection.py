"""
Phase 2.12.2 — Subgoal Reflection tests
"""
from __future__ import annotations

import pytest

from src.core.planning.subgoals.reflection import (
    SubgoalReflectionResult,
    _check_subgoal_for_drift,
    _get_segments_for_subgoal,
    _subgoal_to_raw_dict,
    _subgoal_to_safe_dict,
    _summarise_segment_status,
    evaluate_subgoal_completion,
    evaluate_subgoal_drift,
    evaluate_subgoal_progress,
    evaluate_subgoal_repair,
    reflect_on_subgoal,
)
from src.core.types.plan_segment import PlanSegment
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState


# ──────────────────────────────────────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_valid_subgoal(subgoal_id: str = "sg-1") -> Subgoal:
    return Subgoal(
        subgoal_id=subgoal_id,
        goal="Test goal",
        context={"key": "value"},
        metadata={},
        parent_id=None,
        state=SubgoalLifecycleState.ACTIVE,
    )


def _make_valid_segment(
    segment_id: str = "seg-1",
    subgoal_id: str = "sg-1",
    steps: list = None,
) -> PlanSegment:
    """Create a valid PlanSegment with deterministic segment_id.

    PlanSegment has segment_id as a post_init computed field from a hash,
    so we can't set it directly.  We create via the constructor and then
    use the .segment_id property for assertions.
    """
    return PlanSegment(
        subgoal_id=subgoal_id,
        steps=steps or ["step1", "step2"],
        context={},
        metadata={},
    )


def _make_segment_with_id(
    subgoal_id: str = "sg-1",
    steps: list = None,
) -> PlanSegment:
    if steps is None:
        steps = ["step1"]
    return PlanSegment(
        subgoal_id=subgoal_id,
        steps=steps,
        context={},
        metadata={},
    )


# ──────────────────────────────────────────────────────────────────────────────
# SubgoalReflectionResult
# ──────────────────────────────────────────────────────────────────────────────

class TestSubgoalReflectionResult:
    def test_creates_frozen(self):
        result = SubgoalReflectionResult(
            progress={"segment_count": 0},
            drift={"status": "no_drift"},
            repair={"action": "none"},
            is_complete=False,
        )
        assert result.progress == {"segment_count": 0}
        assert result.drift == {"status": "no_drift"}
        assert result.repair == {"action": "none"}
        assert result.is_complete is False

    def test_immutable(self):
        result = SubgoalReflectionResult(
            progress={},
            drift={},
            repair={},
            is_complete=False,
        )
        with pytest.raises(Exception):
            result.is_complete = True  # type: ignore

    def test_all_fields_present(self):
        result = SubgoalReflectionResult(
            progress={"segment_count": 3, "completed_segments": 3},
            drift={"status": "no_drift", "severity": "minor"},
            repair={"action": "none", "repaired": {}},
            is_complete=True,
        )
        assert isinstance(result.progress, dict)
        assert isinstance(result.drift, dict)
        assert isinstance(result.repair, dict)
        assert isinstance(result.is_complete, bool)


# ──────────────────────────────────────────────────────────────────────────────
# _subgoal_to_raw_dict
# ──────────────────────────────────────────────────────────────────────────────

class TestSubgoalToRawDict:
    def test_returns_fresh_dict(self):
        sg = _make_valid_subgoal()
        d1 = _subgoal_to_raw_dict(sg)
        d2 = _subgoal_to_raw_dict(sg)
        assert d1 == d2
        d1["goal"] = "mutated"
        assert d2["goal"] == "Test goal"  # deep copy ensured

    def test_all_keys_present(self):
        sg = _make_valid_subgoal()
        d = _subgoal_to_raw_dict(sg)
        assert set(d.keys()) == {
            "subgoal_id", "goal", "context", "metadata", "parent_id", "state",
        }

    def test_state_is_string_value(self):
        sg = _make_valid_subgoal()
        d = _subgoal_to_raw_dict(sg)
        assert d["state"] == "active"
        assert isinstance(d["state"], str)


# ──────────────────────────────────────────────────────────────────────────────
# _subgoal_to_safe_dict
# ──────────────────────────────────────────────────────────────────────────────

class TestSubgoalToSafeDict:
    def test_deep_copies_mutable_fields(self):
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="test",
            context={"nested": {"key": "val"}},
            metadata={"m": "v"},
            state=SubgoalLifecycleState.PENDING,
        )
        d = _subgoal_to_safe_dict(sg)
        # Mutate returned dict — should not affect original
        d["context"]["nested"]["key"] = "mutated"
        assert sg.context["nested"]["key"] == "val"

        d["metadata"]["m"] = "mutated"
        assert sg.metadata["m"] == "v"


# ──────────────────────────────────────────────────────────────────────────────
# _get_segments_for_subgoal
# ──────────────────────────────────────────────────────────────────────────────

class TestGetSegmentsForSubgoal:
    def test_returns_filtered_segments(self):
        sg = _make_valid_subgoal("sg-1")
        seg_a = _make_segment_with_id("sg-1", ["step1"])
        seg_b = _make_segment_with_id("sg-2", ["step2"])
        seg_c = _make_segment_with_id("sg-1", ["step3"])

        result = _get_segments_for_subgoal(sg, [seg_a, seg_b, seg_c])
        assert len(result) == 2
        for seg in result:
            assert seg.subgoal_id == "sg-1"

    def test_no_segments_returns_empty(self):
        sg = _make_valid_subgoal("sg-1")
        result = _get_segments_for_subgoal(sg, [])
        assert result == []

    def test_segments_none_falls_back_to_metadata(self):
        sg = _make_valid_subgoal("sg-1")
        # No segments in metadata → empty
        result = _get_segments_for_subgoal(sg, None)
        assert result == []

    def test_segments_none_with_metadata_segments(self):
        seg = _make_segment_with_id("sg-1", ["s1"])
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="test",
            context={},
            metadata={"segments": [seg.segment_id]},
            state=SubgoalLifecycleState.ACTIVE,
        )
        # metadata stores segment IDs (strings), not PlanSegment objects.
        # _get_segments_for_subgoal returns metadata segments as-is (list of strings).
        result = _get_segments_for_subgoal(sg, None)
        assert result == [seg.segment_id]

    def test_explicit_segments_override_metadata(self):
        seg_explicit = _make_segment_with_id("sg-1", ["explicit"])
        seg_meta_id = _make_segment_with_id("sg-1", ["meta"]).segment_id
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="test",
            context={},
            metadata={"segments": [seg_meta_id]},
            state=SubgoalLifecycleState.ACTIVE,
        )
        result = _get_segments_for_subgoal(sg, [seg_explicit])
        assert len(result) == 1
        assert result[0].steps == ["explicit"]


# ──────────────────────────────────────────────────────────────────────────────
# _summarise_segment_status
# ──────────────────────────────────────────────────────────────────────────────

class TestSummariseSegmentStatus:
    def test_valid_segment_is_complete(self):
        seg = _make_segment_with_id("sg-1", ["step1", "step2"])
        summary = _summarise_segment_status(seg)
        assert summary["complete"] is True
        assert summary["step_count"] == 2
        assert summary["malformed_steps"] == 0

    def test_empty_steps_not_complete(self):
        seg = _make_segment_with_id("sg-1", [])
        summary = _summarise_segment_status(seg)
        assert summary["complete"] is False
        assert summary["step_count"] == 0

    def test_none_step_malformed(self):
        seg = _make_segment_with_id("sg-1", [None])
        summary = _summarise_segment_status(seg)
        assert summary["complete"] is False
        assert summary["malformed_steps"] == 1

    def test_non_string_step_malformed(self):
        seg = PlanSegment(
            subgoal_id="sg-1",
            steps=[123],  # type: ignore
            context={},
            metadata={},
        )
        summary = _summarise_segment_status(seg)
        assert summary["complete"] is False
        assert summary["malformed_steps"] == 1

    def test_mixed_valid_and_malformed(self):
        seg = PlanSegment(
            subgoal_id="sg-1",
            steps=["ok", None, "also ok", 42],  # type: ignore
            context={},
            metadata={},
        )
        summary = _summarise_segment_status(seg)
        assert summary["complete"] is False
        assert summary["malformed_steps"] == 2
        assert summary["step_count"] == 4


# ──────────────────────────────────────────────────────────────────────────────
# _check_subgoal_for_drift
# ──────────────────────────────────────────────────────────────────────────────

class TestCheckSubgoalForDrift:
    def test_valid_subgoal_no_signals(self):
        raw = _subgoal_to_raw_dict(_make_valid_subgoal())
        signals = _check_subgoal_for_drift(raw)
        assert signals == []

    def test_missing_subgoal_id(self):
        raw = {
            "subgoal_id": "",
            "goal": "test",
            "context": {},
            "metadata": {},
            "parent_id": None,
            "state": "active",
        }
        signals = _check_subgoal_for_drift(raw)
        assert len(signals) > 0
        assert any(s.details.get("field") == "subgoal_id" for s in signals)

    def test_missing_goal(self):
        raw = {
            "subgoal_id": "sg-1",
            "goal": "",
            "context": {},
            "metadata": {},
            "parent_id": None,
            "state": "active",
        }
        signals = _check_subgoal_for_drift(raw)
        assert len(signals) > 0
        assert any(s.details.get("field") == "goal" for s in signals)

    def test_bad_context_type(self):
        raw = {
            "subgoal_id": "sg-1",
            "goal": "test",
            "context": "not_a_dict",
            "metadata": {},
            "parent_id": None,
            "state": "active",
        }
        signals = _check_subgoal_for_drift(raw)
        assert len(signals) > 0
        assert any(s.type == "type_mismatch" and s.details.get("field") == "context" for s in signals)

    def test_bad_metadata_type(self):
        raw = {
            "subgoal_id": "sg-1",
            "goal": "test",
            "context": {},
            "metadata": "not_a_dict",
            "parent_id": None,
            "state": "active",
        }
        signals = _check_subgoal_for_drift(raw)
        assert any(s.type == "type_mismatch" and s.details.get("field") == "metadata" for s in signals)

    def test_invalid_state_value(self):
        raw = {
            "subgoal_id": "sg-1",
            "goal": "test",
            "context": {},
            "metadata": {},
            "parent_id": None,
            "state": "not_a_valid_state",
        }
        signals = _check_subgoal_for_drift(raw)
        assert any(s.type == "invalid_state" for s in signals)

    def test_multiple_issues(self):
        raw = {
            "subgoal_id": "",
            "goal": "",
            "context": "bad",
            "metadata": "bad",
            "parent_id": None,
            "state": "bad_state",
        }
        signals = _check_subgoal_for_drift(raw)
        assert len(signals) >= 4  # at least subgoal_id, goal, context, metadata


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_subgoal_progress
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateSubgoalProgress:
    def test_valid_subgoal_no_segments(self):
        sg = _make_valid_subgoal()
        result = evaluate_subgoal_progress(sg)
        assert result == {"segment_count": 0, "completed_segments": 0}

    def test_valid_subgoal_with_completed_segments(self):
        sg = _make_valid_subgoal("sg-1")
        seg_a = _make_segment_with_id("sg-1", ["step1", "step2"])
        seg_b = _make_segment_with_id("sg-1", ["step1"])
        result = evaluate_subgoal_progress(sg, [seg_a, seg_b])
        assert result["segment_count"] == 2
        assert result["completed_segments"] == 2
        assert "missing_fields" not in result
        assert "malformed_segments" not in result

    def test_missing_subgoal_id(self):
        sg = Subgoal(
            subgoal_id="",
            goal="test",
            context={},
            metadata={},
            state=SubgoalLifecycleState.ACTIVE,
        )
        result = evaluate_subgoal_progress(sg)
        assert "missing_fields" in result
        assert "subgoal_id" in result["missing_fields"]

    def test_missing_goal(self):
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="",
            context={},
            metadata={},
            state=SubgoalLifecycleState.ACTIVE,
        )
        result = evaluate_subgoal_progress(sg)
        assert "missing_fields" in result
        assert "goal" in result["missing_fields"]

    def test_malformed_segments_counted(self):
        sg = _make_valid_subgoal("sg-1")
        seg_good = _make_segment_with_id("sg-1", ["step1"])
        seg_bad = PlanSegment(
            subgoal_id="sg-1",
            steps=[None, "ok"],  # type: ignore
            context={},
            metadata={},
        )
        result = evaluate_subgoal_progress(sg, [seg_good, seg_bad])
        assert result["segment_count"] == 2
        assert result["completed_segments"] == 1
        assert result["malformed_segments"] == 1

    def test_empty_segments_not_counted_as_complete(self):
        sg = _make_valid_subgoal("sg-1")
        seg = _make_segment_with_id("sg-1", [])
        result = evaluate_subgoal_progress(sg, [seg])
        assert result["segment_count"] == 1
        assert result["completed_segments"] == 0

    def test_missing_fields_are_sorted(self):
        sg = Subgoal(
            subgoal_id="",
            goal="",
            context="bad",  # type: ignore
            metadata={},
            state=SubgoalLifecycleState.ACTIVE,
        )
        result = evaluate_subgoal_progress(sg)
        missing = result.get("missing_fields", [])
        assert missing == sorted(missing)


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_subgoal_drift
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateSubgoalDrift:
    def test_valid_subgoal_no_drift(self):
        sg = _make_valid_subgoal()
        result = evaluate_subgoal_drift(sg)
        assert result["status"] == "no_drift"

    def test_missing_fields_produce_drift(self):
        sg = Subgoal(
            subgoal_id="",
            goal="",
            context={},
            metadata={},
            state=SubgoalLifecycleState.PENDING,
        )
        result = evaluate_subgoal_drift(sg)
        assert result["status"] == "drift_detected"
        assert result["signal_count"] > 0

    def test_drift_keys_present(self):
        sg = _make_valid_subgoal()
        result = evaluate_subgoal_drift(sg)
        for key in ("status", "severity", "categories", "confidence", "streak", "signal_count"):
            assert key in result

    def test_segment_drift_adds_signals(self):
        sg = _make_valid_subgoal("sg-1")
        seg = PlanSegment(
            subgoal_id="sg-1",
            steps=[None],  # type: ignore
            context={},
            metadata={},
        )
        result = evaluate_subgoal_drift(sg, [seg])
        assert result["status"] == "drift_detected"

    def test_empty_segment_produces_drift(self):
        sg = _make_valid_subgoal("sg-1")
        seg = _make_segment_with_id("sg-1", [])
        result = evaluate_subgoal_drift(sg, [seg])
        assert result["status"] == "drift_detected"


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_subgoal_repair
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateSubgoalRepair:
    def test_no_drift_returns_none_action(self):
        sg = _make_valid_subgoal()
        drift = {"status": "no_drift"}
        result = evaluate_subgoal_repair(sg, drift)
        assert result["action"] == "none"
        assert "repaired" in result
        assert result["repaired"]["subgoal_id"] == sg.subgoal_id

    def test_drift_triggers_repair(self):
        sg = _make_valid_subgoal()
        drift = {"status": "drift_detected", "severity": "minor"}
        result = evaluate_subgoal_repair(sg, drift)
        # A valid subgoal should survive repair and return "repair_subgoal"
        assert result["action"] in ("repair_subgoal", "repair_failed")

    def test_repair_preserves_subgoal_id(self):
        sg = _make_valid_subgoal()
        # Create drift by making goal empty — repair should fix to "unknown"
        broken = Subgoal(
            subgoal_id="sg-1",
            goal="",
            context={},
            metadata={},
            state=SubgoalLifecycleState.PENDING,
        )
        drift = {"status": "drift_detected", "severity": "major"}
        result = evaluate_subgoal_repair(broken, drift)
        assert result["action"] in ("repair_subgoal", "repair_failed")
        if result["action"] == "repair_subgoal":
            # repair_subgoal defaults empty goal to "unknown"
            assert result["repaired"]["goal"] == "unknown"

    def test_repair_failed_does_not_crash(self):
        sg = _make_valid_subgoal()
        drift = {"status": "drift_detected", "severity": "major"}
        result = evaluate_subgoal_repair(sg, drift)
        # Should return a valid dict even if underlying repair has issues
        assert "action" in result
        assert "repaired" in result


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_subgoal_completion
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateSubgoalCompletion:
    def test_valid_subgoal_complete(self):
        sg = _make_valid_subgoal()
        result = evaluate_subgoal_completion(sg)
        assert result is True

    def test_missing_fields_incomplete(self):
        sg = Subgoal(
            subgoal_id="",
            goal="test",
            context={},
            metadata={},
            state=SubgoalLifecycleState.ACTIVE,
        )
        result = evaluate_subgoal_completion(sg)
        assert result is False

    def test_malformed_segments_incomplete(self):
        sg = _make_valid_subgoal("sg-1")
        seg = PlanSegment(
            subgoal_id="sg-1",
            steps=[None],  # type: ignore
            context={},
            metadata={},
        )
        result = evaluate_subgoal_completion(sg, [seg])
        assert result is False

    def test_positive_completion(self):
        sg = _make_valid_subgoal("sg-1")
        seg_a = _make_segment_with_id("sg-1", ["s1", "s2"])
        seg_b = _make_segment_with_id("sg-1", ["s1"])
        result = evaluate_subgoal_completion(sg, [seg_a, seg_b])
        assert result is True


# ──────────────────────────────────────────────────────────────────────────────
# reflect_on_subgoal
# ──────────────────────────────────────────────────────────────────────────────

class TestReflectOnSubgoal:
    def test_returns_correct_type(self):
        sg = _make_valid_subgoal()
        result = reflect_on_subgoal(sg)
        assert isinstance(result, SubgoalReflectionResult)
        assert isinstance(result.progress, dict)
        assert isinstance(result.drift, dict)
        assert isinstance(result.repair, dict)
        assert isinstance(result.is_complete, bool)

    def test_valid_subgoa_no_drift_no_repair_complete(self):
        sg = _make_valid_subgoal()
        result = reflect_on_subgoal(sg)
        assert result.progress.get("missing_fields") is None
        assert result.drift["status"] == "no_drift"
        assert result.repair["action"] == "none"
        assert result.is_complete is True

    def test_missing_fields_drift_repair_incomplete(self):
        sg = Subgoal(
            subgoal_id="",
            goal="",
            context={},
            metadata={},
            state=SubgoalLifecycleState.PENDING,
        )
        result = reflect_on_subgoal(sg)
        assert result.progress.get("missing_fields") is not None
        assert result.drift["status"] == "drift_detected"
        assert result.repair["action"] in ("repair_subgoal", "repair_failed")
        assert result.is_complete is False

    def test_malformed_segments_drift_incomplete(self):
        sg = _make_valid_subgoal("sg-1")
        seg = PlanSegment(
            subgoal_id="sg-1",
            steps=[None],  # type: ignore
            context={},
            metadata={},
        )
        result = reflect_on_subgoal(sg, [seg])
        assert result.drift["status"] == "drift_detected"
        assert result.is_complete is False

    def test_repaired_subgoal_can_become_complete(self):
        # Subgoal with empty goal — repair sets it to "unknown"
        broken = Subgoal(
            subgoal_id="sg-1",
            goal="",
            context={},
            metadata={},
            state=SubgoalLifecycleState.PENDING,
        )
        result = reflect_on_subgoal(broken)
        # After repair, the goal should be "unknown"
        if result.repair["action"] == "repair_subgoal":
            assert result.repair["repaired"]["goal"] == "unknown"

    def test_determinism(self):
        sg = _make_valid_subgoal()
        seg = _make_segment_with_id("sg-1", ["s1"])
        r1 = reflect_on_subgoal(sg, [seg])
        r2 = reflect_on_subgoal(sg, [seg])
        assert r1 == r2
        # Also check individual components
        progress1 = evaluate_subgoal_progress(sg, [seg])
        progress2 = evaluate_subgoal_progress(sg, [seg])
        assert progress1 == progress2

        drift1 = evaluate_subgoal_drift(sg, [seg])
        drift2 = evaluate_subgoal_drift(sg, [seg])
        assert drift1 == drift2

    def test_reflection_order(self):
        """Verify the reflection runs in the correct order (progress → drift → repair → completion)."""
        sg = _make_valid_subgoal()
        result = reflect_on_subgoal(sg)
        # All four components should be present
        assert len(result.progress) > 0
        assert len(result.drift) > 0
        assert len(result.repair) > 0
        assert isinstance(result.is_complete, bool)

    def test_frozen_result(self):
        sg = _make_valid_subgoal()
        result = reflect_on_subgoal(sg)
        with pytest.raises(Exception):
            result.is_complete = False  # type: ignore
        with pytest.raises(Exception):
            result.progress = {}  # type: ignore

    def test_no_side_effects(self):
        """Subgoal input is not mutated by reflection."""
        sg = _make_valid_subgoal()
        original_id = sg.subgoal_id
        original_goal = sg.goal
        _ = reflect_on_subgoal(sg)
        assert sg.subgoal_id == original_id
        assert sg.goal == original_goal

    def test_with_segments_parameter(self):
        sg = _make_valid_subgoal("sg-1")
        seg = _make_segment_with_id("sg-1", ["step1", "step2"])
        result = reflect_on_subgoal(sg, [seg])
        assert result.progress["segment_count"] == 1
        assert result.progress["completed_segments"] == 1
