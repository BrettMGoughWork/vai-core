"""
Tests for Phase 2.8.1 — Semantic Validator.

Covers:
  - SemanticMismatch frozen dataclass validation
  - validate_semantics() pure function
  - step_mismatch detection
  - plan_mismatch detection
  - subgoal_mismatch detection
  - memory_mismatch detection
  - Multiple mismatches → deterministic ordering
  - Confidence values correct
  - Details JSON‑safe
  - No mutation of inputs
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import pytest

from src.core.memory.plan_memory_types import PlanMemoryRecord
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.core.planning.agent_loop.agent_loop_types import MemorySnapshot
from src.core.planning.drift.semantic_signal_types import SemanticMismatch
from src.core.planning.drift.semantic_validator import validate_semantics
from src.core.planning.models.plan import Plan
from src.core.types.plan_segment import PlanSegment
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState

NOW = "2025-06-10T00:00:00+00:00"


# ── helpers ─────────────────────────────────────────────────────────────────


def _plan(intent: str = "create a file") -> Plan:
    return Plan(
        intent=intent,
        targetskillid="test-skill",
        arguments={},
        reasoning_summary="test plan",
    )


def _step(steps: List[str] | None = None) -> PlanSegment:
    return PlanSegment(
        subgoal_id="sg-1",
        steps=steps or ["execute the operation"],
        context={},
        metadata={},
    )


def _subgoal(goal: str = "complete the task successfully") -> Subgoal:
    return Subgoal.new(
        goal=goal,
        context={},
        metadata={},
    )


def _segment(
    segment_id: str = "seg-1",
    subgoal_id: str = "sg-1",
    last_output: Any = None,
    content: List[str] | None = None,
) -> SegmentMemoryRecord:
    return SegmentMemoryRecord(
        segment_id=segment_id,
        parent_id=None,
        subgoal_id=subgoal_id,
        state=None,
        content=content or ["step-1"],
        created_at=NOW,
        context={},
        metadata={},
        last_output=last_output,
        behavioural_signals=[],
    )


def _memory(
    subgoals: Tuple[SubgoalMemoryRecord, ...] = (),
    segments: Tuple[SegmentMemoryRecord, ...] = (),
    plans: Tuple[PlanMemoryRecord, ...] = (),
) -> MemorySnapshot:
    return MemorySnapshot(
        subgoals=subgoals,
        segments=segments,
        plans=plans,
        drift_events=(),
        snapshot_timestamp=NOW,
    )


def _sg_mem(*, goal: str = "test goal", subgoal_id: str = "sg-1") -> SubgoalMemoryRecord:
    return SubgoalMemoryRecord(
        subgoal_id=subgoal_id,
        parent_id=None,
        state="active",
        goal=goal,
        context={},
        metadata={},
        created_at=1,
    )


def _plan_mem(*, intent: str = "test intent", plan_id: str = "p-1") -> PlanMemoryRecord:
    return PlanMemoryRecord(
        plan_id=plan_id,
        subgoal_id="sg-1",
        segments=[],
        created_at=NOW,
        metadata={},
        intent=intent,
        targetskillid="test",
        arguments={},
        reasoning_summary="test",
    )


# =============================================================================
# SemanticMismatch dataclass
# =============================================================================


class TestSemanticMismatchDataclass:
    """Validate frozen dataclass constraints."""

    def test_construction_and_serialisation(self):
        m = SemanticMismatch(
            type="step_mismatch",
            confidence=0.7,
            details={"reason": "test"},
        )
        assert m.type == "step_mismatch"
        assert m.confidence == 0.7
        assert m.details == {"reason": "test"}
        # JSON‑safe
        dumped = json.dumps({"type": m.type, "confidence": m.confidence, "details": m.details})
        assert isinstance(dumped, str)

    def test_confidence_below_zero_raises(self):
        with pytest.raises(ValueError):
            SemanticMismatch(type="step_mismatch", confidence=-0.1, details={})

    def test_confidence_above_one_raises(self):
        with pytest.raises(ValueError):
            SemanticMismatch(type="step_mismatch", confidence=1.1, details={})

    def test_confidence_zero_allowed(self):
        m = SemanticMismatch(type="step_mismatch", confidence=0.0, details={})
        assert m.confidence == 0.0

    def test_confidence_one_allowed(self):
        m = SemanticMismatch(type="step_mismatch", confidence=1.0, details={})
        assert m.confidence == 1.0

    def test_frozen(self):
        m = SemanticMismatch(type="step_mismatch", confidence=0.7, details={})
        with pytest.raises(Exception):
            m.confidence = 0.5  # type: ignore[misc]

    def test_details_deep_copied(self):
        d = {"x": [1, 2, 3]}
        m = SemanticMismatch(type="step_mismatch", confidence=0.7, details=d)
        d["x"].append(4)
        assert m.details["x"] == [1, 2, 3]


# =============================================================================
# validate_semantics — no mismatches
# =============================================================================


class TestNoMismatches:
    """When output is healthy, no mismatches should be emitted."""

    def test_successful_output_no_mismatches(self):
        plan = _plan(intent="create a file")
        step = _step(steps=["create the target file"])
        subg = _subgoal(goal="complete file creation")
        seg = _segment(last_output={"success": True, "file": "data.txt"})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        assert result == []

    def test_neutral_output_no_contradiction(self):
        plan = _plan(intent="fetch data")
        step = _step(steps=["retrieve the records"])
        subg = _subgoal(goal="get the data")
        seg = _segment(last_output={"records": [1, 2, 3]})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        assert result == []

    def test_dict_output_with_data_no_mismatches(self):
        plan = _plan(intent="return result")
        step = _step(steps=["compute and return"])
        subg = _subgoal(goal="get result")
        seg = _segment(last_output={"count": 42, "status": "ok"})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        assert result == []


# =============================================================================
# step_mismatch
# =============================================================================


class TestStepMismatch:
    """Detection of output misalignment with step description."""

    def test_negative_output_vs_positive_step(self):
        plan = _plan(intent="create a file")
        step = _step(steps=["create the file and return success"])
        subg = _subgoal(goal="complete creation")
        seg = _segment(last_output={"success": False, "error": "not found"})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "step_mismatch" in types

    def test_empty_output_vs_positive_step(self):
        plan = _plan(intent="fetch data")
        step = _step(steps=["return the fetched records"])
        subg = _subgoal(goal="get data")
        seg = _segment(last_output={})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "step_mismatch" in types

    def test_null_output_vs_positive_step(self):
        plan = _plan(intent="fetch data")
        step = _step(steps=["return the results"])
        subg = _subgoal(goal="get results")
        seg = _segment(last_output=None)
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "step_mismatch" in types

    def test_missing_expected_fields(self):
        plan = _plan(intent="return user")
        step = _step(steps=['return a dict with fields "username" and "email"'])
        subg = _subgoal(goal="get user info")
        seg = _segment(last_output={"username": "alice"})  # missing email
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "step_mismatch" in types

    def test_empty_string_step_no_mismatch(self):
        """Empty step descriptions should not produce false positives."""
        plan = _plan(intent="do something")
        step = _step(steps=[""])
        subg = _subgoal(goal="something")
        seg = _segment(last_output={"success": False})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "step_mismatch" not in types  # step text empty → skip

    def test_step_mismatch_confidence(self):
        plan = _plan(intent="create file")
        step = _step(steps=["create the file successfully"])
        subg = _subgoal(goal="create file")
        seg = _segment(last_output={"success": False, "error": "disk full"})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        sm = [m for m in result if m.type == "step_mismatch"]
        assert len(sm) == 1
        assert sm[0].confidence == 0.7

    def test_step_mismatch_details_json_safe(self):
        plan = _plan(intent="create file")
        step = _step(steps=["create the file"])
        subg = _subgoal(goal="create file")
        seg = _segment(last_output={"success": False})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        for m in result:
            json.dumps(m.details)


# =============================================================================
# plan_mismatch
# =============================================================================


class TestPlanMismatch:
    """Detection of output misalignment with plan intent."""

    def test_failure_output_vs_positive_intent(self):
        plan = _plan(intent="create a new file")
        step = _step(steps=["execute"])
        subg = _subgoal(goal="create file")
        seg = _segment(last_output={"error": "permission denied", "detail": "cannot write"})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "plan_mismatch" in types

    def test_empty_output_vs_positive_intent(self):
        plan = _plan(intent="return the generated report")
        step = _step(steps=["generate report"])
        subg = _subgoal(goal="get report")
        seg = _segment(last_output={})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "plan_mismatch" in types

    def test_plan_mismatch_confidence(self):
        plan = _plan(intent="create database entry")
        step = _step(steps=["insert record"])
        subg = _subgoal(goal="insert data")
        seg = _segment(last_output={"success": False, "error": "duplicate key"})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        pm = [m for m in result if m.type == "plan_mismatch"]
        assert len(pm) == 1
        assert pm[0].confidence == 0.8

    def test_plan_mismatch_details_json_safe(self):
        plan = _plan(intent="create file")
        step = _step(steps=["execute"])
        subg = _subgoal(goal="create file")
        seg = _segment(last_output={"error": "failed"})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        for m in result:
            json.dumps(m.details)

    def test_no_plan_mismatch_when_intent_empty(self):
        plan = _plan(intent="")
        step = _step(steps=["do something"])
        subg = _subgoal(goal="something")
        seg = _segment(last_output={"error": "failed"})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "plan_mismatch" not in types


# =============================================================================
# subgoal_mismatch
# =============================================================================


class TestSubgoalMismatch:
    """Detection of output misalignment with subgoal goal."""

    def test_failure_output_vs_positive_goal(self):
        plan = _plan(intent="execute")
        step = _step(steps=["run operation"])
        subg = _subgoal(goal="return the processed data")
        seg = _segment(last_output={"success": False, "error": "processing failed"})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "subgoal_mismatch" in types

    def test_empty_output_vs_positive_goal(self):
        plan = _plan(intent="execute")
        step = _step(steps=["run"])
        subg = _subgoal(goal="produce the output file")
        seg = _segment(last_output={})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "subgoal_mismatch" in types

    def test_success_false_vs_goal(self):
        plan = _plan(intent="execute")
        step = _step(steps=["do it"])
        subg = _subgoal(goal="complete the task successfully")
        seg = _segment(last_output={"success": False})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "subgoal_mismatch" in types

    def test_subgoal_mismatch_confidence(self):
        plan = _plan(intent="execute")
        step = _step(steps=["run"])
        subg = _subgoal(goal="return data")
        seg = _segment(last_output={"success": False})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        sm = [m for m in result if m.type == "subgoal_mismatch"]
        assert len(sm) == 1
        assert sm[0].confidence == 0.9

    def test_subgoal_mismatch_details_json_safe(self):
        plan = _plan(intent="execute")
        step = _step(steps=["run"])
        subg = _subgoal(goal="return data")
        seg = _segment(last_output={"success": False})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        for m in result:
            json.dumps(m.details)

    def test_no_subgoal_mismatch_when_goal_empty(self):
        plan = _plan(intent="execute")
        step = _step(steps=["run"])
        subg = Subgoal.new(goal="", context={}, metadata={})
        seg = _segment(last_output={"error": "failed"})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "subgoal_mismatch" not in types


# =============================================================================
# memory_mismatch
# =============================================================================


class TestMemoryMismatch:
    """Detection of output contradicting memory facts."""

    def test_failure_output_contradicts_memory_success(self):
        plan = _plan(intent="execute")
        step = _step(steps=["run"])
        subg = _subgoal(goal="do it")
        seg = _segment(last_output={"success": False, "error": "unexpected"})
        mem = _memory(
            subgoals=(_sg_mem(goal="completed successfully"),),
        )

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "memory_mismatch" in types

    def test_empty_output_with_rich_memory(self):
        plan = _plan(intent="execute")
        step = _step(steps=["run"])
        subg = _subgoal(goal="do it")
        seg = _segment(last_output={})
        mem = _memory(
            subgoals=(
                _sg_mem(goal="fact 1", subgoal_id="sg-1"),
                _sg_mem(goal="fact 2", subgoal_id="sg-2"),
                _sg_mem(goal="fact 3", subgoal_id="sg-3"),
            ),
        )

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "memory_mismatch" in types

    def test_memory_mismatch_confidence(self):
        plan = _plan(intent="execute")
        step = _step(steps=["run"])
        subg = _subgoal(goal="do it")
        seg = _segment(last_output={"success": False})
        mem = _memory(
            subgoals=(_sg_mem(goal="completed"),),
        )

        result = validate_semantics(step, seg, plan, subg, mem)
        mm = [m for m in result if m.type == "memory_mismatch"]
        assert len(mm) == 1
        assert mm[0].confidence == 0.6

    def test_memory_mismatch_details_json_safe(self):
        plan = _plan(intent="execute")
        step = _step(steps=["run"])
        subg = _subgoal(goal="do it")
        seg = _segment(last_output={"success": False})
        mem = _memory(
            subgoals=(_sg_mem(goal="completed"),),
        )

        result = validate_semantics(step, seg, plan, subg, mem)
        for m in result:
            json.dumps(m.details)

    def test_empty_memory_no_mismatch(self):
        plan = _plan(intent="execute")
        step = _step(steps=["run"])
        subg = _subgoal(goal="do it")
        seg = _segment(last_output={"success": False})
        mem = _memory()  # empty

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        assert "memory_mismatch" not in types


# =============================================================================
# multiple mismatches → deterministic ordering
# =============================================================================


class TestDeterministicOrdering:
    """Multiple mismatches must be emitted in deterministic order."""

    def test_all_four_mismatches_emitted(self):
        plan = _plan(intent="create file and return data")
        step = _step(steps=['return a dict with "file" and "status" fields'])
        subg = _subgoal(goal="complete file creation successfully")
        seg = _segment(last_output={"success": False, "error": "disk full"})
        mem = _memory(
            subgoals=(_sg_mem(goal="file creation succeeded"),),
        )

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]

        # All four should be present
        for expected in ("step_mismatch", "plan_mismatch", "subgoal_mismatch", "memory_mismatch"):
            assert expected in types, f"Missing {expected} in {types}"

    def test_deterministic_order(self):
        plan = _plan(intent="create file and return data")
        step = _step(steps=['return a dict with "file" and "status" fields'])
        subg = _subgoal(goal="complete file creation successfully")
        seg = _segment(last_output={"success": False, "error": "disk full"})
        mem = _memory(
            subgoals=(_sg_mem(goal="file creation succeeded"),),
        )

        result1 = validate_semantics(step, seg, plan, subg, mem)
        result2 = validate_semantics(step, seg, plan, subg, mem)

        types1 = [m.type for m in result1]
        types2 = [m.type for m in result2]
        assert types1 == types2

    def test_order_matches_spec(self):
        """Order must be: step, plan, subgoal, memory."""
        plan = _plan(intent="create file and return data")
        step = _step(steps=['return a dict with "file" and "status" fields'])
        subg = _subgoal(goal="complete file creation successfully")
        seg = _segment(last_output={"success": False, "error": "disk full"})
        mem = _memory(
            subgoals=(_sg_mem(goal="file creation succeeded"),),
        )

        result = validate_semantics(step, seg, plan, subg, mem)
        types = [m.type for m in result]
        expected_order = ["step_mismatch", "plan_mismatch", "subgoal_mismatch", "memory_mismatch"]

        # Filter to only present types and verify relative order is correct
        filtered = [t for t in expected_order if t in types]
        assert filtered == types, f"Expected order {expected_order}, got {types}"


# =============================================================================
# no mutation of inputs
# =============================================================================


class TestNoMutation:
    """validate_semantics must not mutate any input objects."""

    def test_no_mutation_of_step(self):
        plan = _plan(intent="create file")
        step = _step(steps=["create file"])
        subg = _subgoal(goal="create file")
        seg = _segment(last_output={"success": False})
        mem = _memory()

        original_steps = list(step.steps)
        original_context = dict(step.context)

        validate_semantics(step, seg, plan, subg, mem)

        assert step.steps == original_steps
        assert step.context == original_context

    def test_no_mutation_of_plan(self):
        plan = _plan(intent="create file")
        step = _step(steps=["run"])
        subg = _subgoal(goal="create")
        seg = _segment(last_output={"success": False})
        mem = _memory()

        original_intent = plan.intent
        original_args = dict(plan.arguments)

        validate_semantics(step, seg, plan, subg, mem)

        assert plan.intent == original_intent
        assert plan.arguments == original_args

    def test_no_mutation_of_subgoal(self):
        plan = _plan(intent="create")
        step = _step(steps=["run"])
        subg = _subgoal(goal="create file")
        seg = _segment(last_output={"success": False})
        mem = _memory()

        original_goal = subg.goal
        original_context = dict(subg.context)

        validate_semantics(step, seg, plan, subg, mem)

        assert subg.goal == original_goal
        assert subg.context == original_context

    def test_no_mutation_of_segment(self):
        plan = _plan(intent="create")
        step = _step(steps=["run"])
        subg = _subgoal(goal="create")
        seg = _segment(last_output={"success": False})
        mem = _memory()

        original_output = seg.last_output

        validate_semantics(step, seg, plan, subg, mem)

        assert seg.last_output == original_output

    def test_no_mutation_of_memory(self):
        plan = _plan(intent="create")
        step = _step(steps=["run"])
        subg = _subgoal(goal="create")
        seg = _segment(last_output={"success": False})
        mem = _memory(subgoals=(_sg_mem(goal="test"),))

        original_count = len(mem.subgoals)

        validate_semantics(step, seg, plan, subg, mem)

        assert len(mem.subgoals) == original_count


# =============================================================================
# JSON‑safe output
# =============================================================================


class TestJsonSafe:
    """All mismatch details must be JSON‑serialisable."""

    def test_all_details_json_dumpable(self):
        plan = _plan(intent="create file and return data")
        step = _step(steps=['return a dict with "file" and "status" fields'])
        subg = _subgoal(goal="complete file creation successfully")
        seg = _segment(last_output={"success": False, "error": "disk full"})
        mem = _memory(
            subgoals=(_sg_mem(goal="file creation succeeded"),),
        )

        result = validate_semantics(step, seg, plan, subg, mem)

        for m in result:
            json.dumps(m.details)

    def test_mismatch_serialisable_to_dict(self):
        plan = _plan(intent="create file")
        step = _step(steps=["create file"])
        subg = _subgoal(goal="create file")
        seg = _segment(last_output={"success": False})
        mem = _memory()

        result = validate_semantics(step, seg, plan, subg, mem)
        for m in result:
            d = {"type": m.type, "confidence": m.confidence, "details": m.details}
            assert json.dumps(d)
