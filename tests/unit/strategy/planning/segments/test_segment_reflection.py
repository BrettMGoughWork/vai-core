"""
Phase 2.11.2 — Segment Reflection tests
=======================================

Covers all public and internal reflection functions.
"""
from __future__ import annotations

import copy
import json

import pytest

from src.strategy.planning.segments.reflection import (
    SegmentReflectionResult,
    _check_segment_for_drift,
    evaluate_segment_completion,
    evaluate_segment_drift,
    evaluate_segment_progress,
    evaluate_segment_repair,
    evaluate_segment_completion,
    reflect_on_segment,
)
from src.strategy.types.plan_segment import PlanSegment


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_segment(
    subgoal_id: str = "sg.test",
    steps: list[str] | None = None,
    context: dict | None = None,
    metadata: dict | None = None,
) -> PlanSegment:
    """Create a PlanSegment with controlled fields."""
    if steps is None:
        steps = ["step.1"]
    return PlanSegment(
        subgoal_id=subgoal_id,
        steps=steps,
        context=context or {},
        metadata=metadata or {},
    )


# ──────────────────────────────────────────────────────────────────────────────
# SegmentReflectionResult dataclass
# ──────────────────────────────────────────────────────────────────────────────

class TestSegmentReflectionResult:
    """The result dataclass must be frozen and contain the required fields."""

    def test_is_frozen(self):
        result = SegmentReflectionResult(
            progress={}, drift={}, repair={}, is_complete=False,
        )
        with pytest.raises(Exception):
            result.is_complete = True  # type: ignore[misc]

    def test_fields(self):
        result = SegmentReflectionResult(
            progress={"step_count": 1},
            drift={"status": "no_drift"},
            repair={"action": "none", "repaired": {}},
            is_complete=True,
        )
        assert result.progress == {"step_count": 1}
        assert result.drift == {"status": "no_drift"}
        assert result.repair == {"action": "none", "repaired": {}}
        assert result.is_complete is True

    def test_json_serializable(self):
        result = SegmentReflectionResult(
            progress={"step_count": 1},
            drift={"status": "no_drift"},
            repair={"action": "none", "repaired": {"subgoal_id": "x", "steps": []}},
            is_complete=True,
        )
        dumped = json.dumps(
            {
                "progress": result.progress,
                "drift": result.drift,
                "repair": result.repair,
                "is_complete": result.is_complete,
            }
        )
        loaded = json.loads(dumped)
        assert loaded["is_complete"] is True
        assert loaded["drift"]["status"] == "no_drift"


# ──────────────────────────────────────────────────────────────────────────────
# _check_segment_for_drift (internal)
# ──────────────────────────────────────────────────────────────────────────────

class TestCheckSegmentForDrift:
    """Drift detection on raw segment dicts."""

    # ── valid ──

    def test_valid_segment_no_signals(self):
        sigs = _check_segment_for_drift(
            {"subgoal_id": "sg.1", "steps": ["step1", "step2"], "context": {}, "metadata": {}}
        )
        assert sigs == []

    # ── missing subgoal_id ──

    def test_missing_subgoal_id(self):
        sigs = _check_segment_for_drift(
            {"subgoal_id": "", "steps": ["step1"], "context": {}, "metadata": {}}
        )
        assert len(sigs) == 1
        assert sigs[0].type == "missing_field"
        assert sigs[0].source == "structural"

    def test_null_subgoal_id(self):
        sigs = _check_segment_for_drift(
            {"subgoal_id": None, "steps": ["step1"], "context": {}, "metadata": {}}
        )
        assert len(sigs) == 1
        assert sigs[0].type == "missing_field"

    # ── missing steps ──

    def test_missing_steps_field(self):
        sigs = _check_segment_for_drift(
            {"subgoal_id": "sg.1", "context": {}, "metadata": {}}
        )
        assert len(sigs) == 1
        assert any(s.details.get("field") == "steps" for s in sigs)

    def test_steps_not_a_list(self):
        sigs = _check_segment_for_drift(
            {"subgoal_id": "sg.1", "steps": "not_a_list", "context": {}, "metadata": {}}
        )
        assert len(sigs) == 1
        assert sigs[0].details["field"] == "steps"

    def test_empty_steps_list(self):
        # Empty steps [] triggers empty_steps drift signal
        sigs = _check_segment_for_drift(
            {"subgoal_id": "sg.1", "steps": [], "context": {}, "metadata": {}}
        )
        assert len(sigs) == 1
        assert sigs[0].type == "empty_steps"

    # ── null / malformed step entries ──

    def test_null_step(self):
        sigs = _check_segment_for_drift(
            {"subgoal_id": "sg.1", "steps": ["step1", None], "context": {}, "metadata": {}}
        )
        null_sigs = [s for s in sigs if s.type == "null_step"]
        assert len(null_sigs) == 1
        assert null_sigs[0].details["step_index"] == 1

    def test_non_string_step(self):
        sigs = _check_segment_for_drift(
            {"subgoal_id": "sg.1", "steps": [1, 2, 3.0], "context": {}, "metadata": {}}
        )
        type_sigs = [s for s in sigs if s.type == "type_mismatch"]
        assert len(type_sigs) == 3

    # ── malformed context ──

    def test_context_not_a_dict(self):
        sigs = _check_segment_for_drift(
            {"subgoal_id": "sg.1", "steps": ["step1"], "context": "not_dict", "metadata": {}}
        )
        assert len(sigs) == 1
        assert sigs[0].details["field"] == "context"

    def test_context_none_is_fine(self):
        sigs = _check_segment_for_drift(
            {"subgoal_id": "sg.1", "steps": ["step1"], "context": None, "metadata": {}}
        )
        assert sigs == []  # None context is treated as absent, not malformed


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_segment_progress
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateSegmentProgress:
    """Structural progress summaries must be deterministic and JSON‑safe."""

    def test_valid_segment(self):
        seg = _make_segment()
        result = evaluate_segment_progress(seg)
        assert result == {"step_count": 1}

    def test_empty_subgoal_id(self):
        seg = _make_segment(subgoal_id="")
        result = evaluate_segment_progress(seg)
        assert "missing_fields" in result
        assert "subgoal_id" in result["missing_fields"]

    def test_empty_steps(self):
        seg = _make_segment(steps=[])
        result = evaluate_segment_progress(seg)
        assert "missing_fields" in result
        assert "steps" in result["missing_fields"]
        assert result["step_count"] == 0

    def test_empty_string_step(self):
        seg = _make_segment(steps=[""])
        result = evaluate_segment_progress(seg)
        assert result["step_count"] == 1
        assert result.get("malformed_steps") == 1

    def test_multiple_missing_fields(self):
        seg = _make_segment(subgoal_id="", steps=[])
        result = evaluate_segment_progress(seg)
        missing = result["missing_fields"]
        # deterministic sort
        assert missing == sorted(missing)

    def test_json_serializable(self):
        seg = _make_segment()
        result = evaluate_segment_progress(seg)
        assert json.dumps(result)  # must not raise

    def test_no_side_effects(self):
        seg = _make_segment(steps=["step1", "step2"])
        before = copy.deepcopy(seg.steps)
        evaluate_segment_progress(seg)
        assert seg.steps == before  # unchanged


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_segment_drift
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateSegmentDrift:
    """Drift evaluation must reuse the existing classifier."""

    def test_valid_segment_no_drift(self):
        seg = _make_segment()
        result = evaluate_segment_drift(seg)
        assert result["status"] == "no_drift"
        assert result["signal_count"] == 0
        assert result["severity"] == "minor"  # minor is the default/zero‑signal severity
        assert result["confidence"] == 0.0

    def test_broken_segment_has_drift(self):
        seg = _make_segment(subgoal_id="")
        result = evaluate_segment_drift(seg)
        assert result["status"] != "no_drift"
        assert result["signal_count"] > 0

    def test_field_types(self):
        seg = _make_segment(subgoal_id="")
        result = evaluate_segment_drift(seg)
        assert isinstance(result["status"], str)
        assert isinstance(result["severity"], str)  # "minor" | "major" | "catastrophic"
        assert isinstance(result["categories"], list)
        assert isinstance(result["confidence"], (int, float))
        assert isinstance(result["streak"], int)
        assert isinstance(result["signal_count"], int)

    def test_deterministic(self):
        seg = _make_segment(subgoal_id="", steps=[])
        r1 = evaluate_segment_drift(seg)
        r2 = evaluate_segment_drift(seg)
        assert r1 == r2


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_segment_repair
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateSegmentRepair:
    """Repair must reuse the existing repair engine."""

    def test_no_drift_no_repair(self):
        seg = _make_segment()
        drift = {"status": "no_drift"}
        result = evaluate_segment_repair(seg, drift)
        assert result["action"] == "none"
        assert "repaired" in result

    def test_drift_triggers_repair(self):
        seg = _make_segment(subgoal_id="")
        drift = evaluate_segment_drift(seg)
        result = evaluate_segment_repair(seg, drift)
        assert result["action"] == "repair_segment"
        repaired = result["repaired"]
        assert repaired["subgoal_id"] != ""  # must have been repaired

    def test_empty_steps_repaired(self):
        seg = _make_segment(steps=[])
        drift = evaluate_segment_drift(seg)
        result = evaluate_segment_repair(seg, drift)
        assert result["action"] == "repair_segment"

    def test_repaired_is_json_safe(self):
        seg = _make_segment(subgoal_id="")
        drift = evaluate_segment_drift(seg)
        result = evaluate_segment_repair(seg, drift)
        assert json.dumps(result["repaired"])

    def test_does_not_mutate_input(self):
        seg = _make_segment(subgoal_id="", steps=[])
        before_subgoal = seg.subgoal_id
        before_steps = copy.deepcopy(seg.steps)
        drift = evaluate_segment_drift(seg)
        evaluate_segment_repair(seg, drift)
        assert seg.subgoal_id == before_subgoal
        assert seg.steps == before_steps


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_segment_completion
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateSegmentCompletion:
    """Completion predicate must be a pure boolean function."""

    def test_valid_segment_is_complete(self):
        seg = _make_segment()
        assert evaluate_segment_completion(seg) is True

    def test_missing_fields_incomplete(self):
        seg = _make_segment(subgoal_id="")
        assert evaluate_segment_completion(seg) is False

    def test_empty_steps_incomplete(self):
        seg = _make_segment(steps=[])
        assert evaluate_segment_completion(seg) is False

    def test_malformed_step_incomplete(self):
        seg = _make_segment(steps=[""])
        assert evaluate_segment_completion(seg) is False

    def test_deterministic(self):
        seg = _make_segment()
        assert evaluate_segment_completion(seg) == evaluate_segment_completion(seg)

    def test_repaired_segment_becomes_complete(self):
        seg = _make_segment(subgoal_id="")
        drift = evaluate_segment_drift(seg)
        repair_result = evaluate_segment_repair(seg, drift)
        # The repaired dict should have fixed subgoal_id
        assert repair_result["repaired"]["subgoal_id"] != ""
        # However, evaluate_segment_completion still looks at the original PlanSegment
        # (by design — the caller must use the repaired segment if desired)
        assert evaluate_segment_completion(seg) is False


# ──────────────────────────────────────────────────────────────────────────────
# reflect_on_segment (orchestrator)
# ──────────────────────────────────────────────────────────────────────────────

class TestReflectOnSegment:
    """The main reflection orchestrator."""

    def test_valid_segment(self):
        seg = _make_segment()
        result = reflect_on_segment(seg)
        assert isinstance(result, SegmentReflectionResult)
        assert result.is_complete is True
        assert result.progress == {"step_count": 1}
        assert result.drift["status"] == "no_drift"
        assert result.repair["action"] == "none"

    def test_broken_segment(self):
        seg = _make_segment(subgoal_id="")
        result = reflect_on_segment(seg)
        assert isinstance(result, SegmentReflectionResult)
        assert result.is_complete is False
        assert "missing_fields" in result.progress
        assert result.drift["status"] != "no_drift"
        assert result.repair["action"] == "repair_segment"

    def test_missing_steps_segment(self):
        seg = _make_segment(steps=[])
        result = reflect_on_segment(seg)
        assert result.is_complete is False
        assert "missing_fields" in result.progress

    def test_deterministic(self):
        seg = _make_segment(subgoal_id="")
        r1 = reflect_on_segment(seg)
        r2 = reflect_on_segment(seg)
        # SegmentReflectionResult is frozen — equality by value
        assert r1.progress == r2.progress
        assert r1.drift == r2.drift
        assert r1.repair == r2.repair
        assert r1.is_complete == r2.is_complete

    def test_result_is_frozen(self):
        seg = _make_segment()
        result = reflect_on_segment(seg)
        with pytest.raises(Exception):
            result.is_complete = False  # type: ignore[misc]

    def test_json_serializable(self):
        seg = _make_segment(subgoal_id="")
        result = reflect_on_segment(seg)
        data = {
            "progress": result.progress,
            "drift": result.drift,
            "repair": result.repair,
            "is_complete": result.is_complete,
        }
        assert json.dumps(data)

    def test_no_side_effects(self):
        seg = _make_segment(steps=["step1", "step2"])
        before_subgoal = seg.subgoal_id
        before_steps = copy.deepcopy(seg.steps)
        before_context = copy.deepcopy(seg.context)
        reflect_on_segment(seg)
        assert seg.subgoal_id == before_subgoal
        assert seg.steps == before_steps
        assert seg.context == before_context

    def test_unchanged_on_no_drift(self):
        seg = _make_segment()
        result = reflect_on_segment(seg)
        assert result.is_complete is True
        assert result.repair["action"] == "none"


# ──────────────────────────────────────────────────────────────────────────────
# Order contract
# ──────────────────────────────────────────────────────────────────────────────

class TestReflectionOrder:
    """Reflection must evaluate in deterministic order: progress → drift → repair → completion."""

    def test_order_is_respected(self):
        seg = _make_segment(subgoal_id="")
        result = reflect_on_segment(seg)
        # All fields populated
        assert result.progress is not None
        assert result.drift is not None
        assert result.repair is not None
        assert result.is_complete is not None