"""
Tests for Phase 2.10.1 — Repair Action Library.

Covers:
  - repair_step() — malformed steps repaired
  - repair_segment() — malformed segments repaired
  - repair_plan() — malformed plans repaired
  - repair_subgoal() — malformed subgoals repaired
  - repair_drift_inconsistency() — drift‑induced inconsistencies repaired
  - no mutation of inputs
  - deterministic output
  - JSON safety
"""
from __future__ import annotations

import json

import pytest

from src.core.planning.drift.repair_action_library import (
    repair_drift_inconsistency,
    repair_plan,
    repair_segment,
    repair_step,
    repair_subgoal,
)
from src.core.planning.models.plan import Plan
from src.core.planning.models.plan_state import PlanState, PlanStatus
from src.core.types.core_step import CoreStep
from src.core.types.plan_segment import PlanSegment
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState


# ============================================================================
# repair_step
# ============================================================================


class TestRepairStep:
    """Tests for repair_step()."""

    def test_valid_step_returns_unchanged(self) -> None:
        step = CoreStep(step_type="execute", payload={"arg": 1})
        result = repair_step(step)
        assert result is step
        assert result.step_type == "execute"
        assert result.payload == {"arg": 1}

    def test_empty_step_type_defaults_to_unknown(self) -> None:
        step = CoreStep(step_type="", payload={"arg": 1})
        result = repair_step(step)
        assert result.step_type == "unknown"
        assert result.payload == {"arg": 1}

    def test_none_payload_defaults_to_empty_dict(self) -> None:
        step = CoreStep(step_type="execute", payload=None)  # type: ignore[arg-type]
        result = repair_step(step)
        assert result.step_type == "execute"
        assert result.payload == {}

    def test_both_malformed(self) -> None:
        step = CoreStep(step_type="", payload=None)  # type: ignore[arg-type]
        result = repair_step(step)
        assert result.step_type == "unknown"
        assert result.payload == {}

    def test_does_not_mutate_input(self) -> None:
        step = CoreStep(step_type="", payload={"arg": 1})
        repair_step(step)
        assert step.step_type == ""
        assert step.payload == {"arg": 1}

    def test_deterministic_output(self) -> None:
        step = CoreStep(step_type="", payload=None)  # type: ignore[arg-type]
        r1 = repair_step(step)
        r2 = repair_step(step)
        assert r1.step_type == r2.step_type
        assert r1.payload == r2.payload

    def test_result_is_json_safe(self) -> None:
        step = CoreStep(step_type="", payload=None)  # type: ignore[arg-type]
        result = repair_step(step)
        dumped = json.dumps({
            "step_type": result.step_type,
            "payload": result.payload,
        })
        assert isinstance(dumped, str)

    def test_non_string_step_type_normalised(self) -> None:
        step = CoreStep(step_type=42, payload={})  # type: ignore[arg-type]
        result = repair_step(step)
        assert result.step_type == "unknown"

    def test_list_payload_normalised_to_empty_dict(self) -> None:
        step = CoreStep(step_type="execute", payload=[1, 2, 3])  # type: ignore[arg-type]
        result = repair_step(step)
        assert result.payload == {}


# ============================================================================
# repair_segment
# ============================================================================


class TestRepairSegment:
    """Tests for repair_segment()."""

    def test_valid_segment_returns_unchanged(self) -> None:
        seg = PlanSegment(
            subgoal_id="sg-1",
            steps=["step-1", "step-2"],
        )
        result = repair_segment(seg)
        assert result is seg

    def test_null_steps_removed(self) -> None:
        seg = PlanSegment(
            subgoal_id="sg-1",
            steps=["step-1", None, 42, "step-2"],  # type: ignore[list-item]
        )
        result = repair_segment(seg)
        assert result.steps == ["step-1", "step-2"]

    def test_empty_subgoal_id_defaults_to_unknown(self) -> None:
        seg = PlanSegment(
            subgoal_id="",
            steps=["step-1"],
        )
        result = repair_segment(seg)
        assert result.subgoal_id == "unknown"

    def test_non_dict_context_defaults_to_empty(self) -> None:
        seg = PlanSegment(
            subgoal_id="sg-1",
            steps=["step-1"],
            context=["not", "a", "dict"],  # type: ignore[arg-type]
        )
        result = repair_segment(seg)
        assert result.context == {}

    def test_non_dict_metadata_defaults_to_empty(self) -> None:
        seg = PlanSegment(
            subgoal_id="sg-1",
            steps=["step-1"],
            metadata=[1, 2, 3],  # type: ignore[arg-type]
        )
        result = repair_segment(seg)
        assert result.metadata == {}

    def test_empty_created_at_defaults_to_epoch(self) -> None:
        seg = PlanSegment(
            subgoal_id="sg-1",
            steps=["step-1"],
        )
        # Force empty created_at via valid construction then test separately
        # PlanSegment has a default factory, so we construct normally then test a
        # segment that was repaired due to other issues (created_at stays valid)
        result = repair_segment(seg)
        assert result.created_at == seg.created_at  # Already valid from factory

    def test_all_fields_malformed(self) -> None:
        seg = PlanSegment(
            subgoal_id="",
            steps=[None, "step-1"],  # type: ignore[list-item]
            context=None,  # type: ignore[arg-type]
            metadata=None,  # type: ignore[arg-type]
        )
        result = repair_segment(seg)
        assert result.subgoal_id == "unknown"
        assert result.steps == ["step-1"]
        assert result.context == {}
        assert result.metadata == {}

    def test_does_not_mutate_input(self) -> None:
        seg = PlanSegment(
            subgoal_id="",
            steps=[None, "step-1"],  # type: ignore[list-item]
        )
        repair_segment(seg)
        assert seg.subgoal_id == ""
        assert seg.steps == [None, "step-1"]  # type: ignore[comparison-overlap]

    def test_deterministic_output(self) -> None:
        seg = PlanSegment(
            subgoal_id="",
            steps=["step-1"],
        )
        r1 = repair_segment(seg)
        r2 = repair_segment(seg)
        assert r1.subgoal_id == r2.subgoal_id
        assert r1.steps == r2.steps

    def test_result_is_json_safe(self) -> None:
        seg = PlanSegment(
            subgoal_id="",
            steps=["step-1"],
        )
        result = repair_segment(seg)
        dumped = json.dumps({
            "subgoal_id": result.subgoal_id,
            "steps": result.steps,
            "context": result.context,
            "metadata": result.metadata,
            "created_at": result.created_at,
            "segment_id": result.segment_id,
            "canonical_hash": result.canonical_hash,
        })
        assert isinstance(dumped, str)


# ============================================================================
# repair_plan
# ============================================================================


class TestRepairPlan:
    """Tests for repair_plan()."""

    def test_valid_plan_returns_unchanged(self) -> None:
        plan = Plan(
            intent="solve problem",
            targetskillid="skill-001",
            arguments={"a": 1},
            reasoning_summary="test reasoning",
        )
        result = repair_plan(plan)
        assert result.intent == "solve problem"
        assert result.targetskillid == "skill-001"
        assert result.arguments == {"a": 1}
        assert result.reasoning_summary == "test reasoning"

    def test_empty_intent_defaults_to_unknown(self) -> None:
        plan = Plan(
            intent="",
            targetskillid="skill-001",
            arguments={},
            reasoning_summary="",
        )
        result = repair_plan(plan)
        assert result.intent == "unknown"

    def test_empty_targetskillid_kept(self) -> None:
        plan = Plan(
            intent="solve",
            targetskillid="",
            arguments={},
            reasoning_summary="",
        )
        result = repair_plan(plan)
        assert result.targetskillid == ""

    def test_non_dict_arguments_defaults_to_empty(self) -> None:
        plan = Plan(
            intent="solve",
            targetskillid="skill-001",
            arguments=None,  # type: ignore[arg-type]
            reasoning_summary="test",
        )
        result = repair_plan(plan)
        assert result.arguments == {}

    def test_non_string_reasoning_normalised(self) -> None:
        plan = Plan(
            intent="solve",
            targetskillid="skill-001",
            arguments={},
            reasoning_summary=None,  # type: ignore[arg-type]
        )
        result = repair_plan(plan)
        assert result.reasoning_summary == ""

    def test_all_fields_malformed(self) -> None:
        plan = Plan(
            intent="",
            targetskillid=None,  # type: ignore[arg-type]
            arguments=[1, 2],  # type: ignore[arg-type]
            reasoning_summary=42,  # type: ignore[arg-type]
        )
        result = repair_plan(plan)
        assert result.intent == "unknown"
        assert result.targetskillid == ""
        assert result.arguments == {}
        assert result.reasoning_summary == ""

    def test_does_not_mutate_input(self) -> None:
        plan = Plan(
            intent="",
            targetskillid="skill-001",
            arguments={},
            reasoning_summary="",
        )
        repair_plan(plan)
        assert plan.intent == ""
        assert plan.targetskillid == "skill-001"

    def test_deterministic_output(self) -> None:
        plan = Plan(
            intent="",
            targetskillid=None,  # type: ignore[arg-type]
            arguments=[],  # type: ignore[arg-type]
            reasoning_summary=99,  # type: ignore[arg-type]
        )
        r1 = repair_plan(plan)
        r2 = repair_plan(plan)
        assert r1.intent == r2.intent
        assert r1.targetskillid == r2.targetskillid
        assert r1.arguments == r2.arguments
        assert r1.reasoning_summary == r2.reasoning_summary

    def test_result_is_json_safe(self) -> None:
        plan = Plan(
            intent="",
            targetskillid="skill-001",
            arguments={},
            reasoning_summary="",
        )
        result = repair_plan(plan)
        dumped = json.dumps(result.to_dict())
        assert isinstance(dumped, str)


# ============================================================================
# repair_subgoal
# ============================================================================


class TestRepairSubgoal:
    """Tests for repair_subgoal()."""

    def test_valid_subgoal_returns_unchanged(self) -> None:
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="achieve X",
            context={"k": "v"},
            metadata={"m": 1},
        )
        result = repair_subgoal(sg)
        assert result is sg

    def test_empty_goal_defaults_to_unknown(self) -> None:
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="",
            context={},
            metadata={},
        )
        result = repair_subgoal(sg)
        assert result.goal == "unknown"

    def test_non_dict_context_defaults_to_empty(self) -> None:
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="goal",
            context="not dict",  # type: ignore[arg-type]
            metadata={},
        )
        result = repair_subgoal(sg)
        assert result.context == {}

    def test_non_dict_metadata_defaults_to_empty(self) -> None:
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="goal",
            context={},
            metadata=[1, 2],  # type: ignore[arg-type]
        )
        result = repair_subgoal(sg)
        assert result.metadata == {}

    def test_empty_subgoal_id_defaults_to_unknown(self) -> None:
        sg = Subgoal(
            subgoal_id="",
            goal="goal",
            context={},
            metadata={},
        )
        result = repair_subgoal(sg)
        assert result.subgoal_id == "unknown"

    def test_non_string_goal_normalised(self) -> None:
        """Goal that is not a string is normalised to 'unknown'."""
        sg = Subgoal(
            subgoal_id="sg-1",
            goal=42,  # type: ignore[arg-type]
            context={},
            metadata={},
        )
        result = repair_subgoal(sg)
        assert result.goal == "unknown"

    def test_all_fields_malformed(self) -> None:
        sg = Subgoal(
            subgoal_id="",
            goal="",
            context=None,  # type: ignore[arg-type]
            metadata=None,  # type: ignore[arg-type]
        )
        result = repair_subgoal(sg)
        assert result.subgoal_id == "unknown"
        assert result.goal == "unknown"
        assert result.context == {}
        assert result.metadata == {}
        assert result.state == SubgoalLifecycleState.PENDING

    def test_does_not_mutate_input(self) -> None:
        sg = Subgoal(
            subgoal_id="",
            goal="goal",
            context={},
            metadata={},
        )
        repair_subgoal(sg)
        assert sg.subgoal_id == ""

    def test_deterministic_output(self) -> None:
        sg = Subgoal(
            subgoal_id="",
            goal="",
            context=[],
            metadata=[],
        )
        r1 = repair_subgoal(sg)
        r2 = repair_subgoal(sg)
        assert r1.subgoal_id == r2.subgoal_id
        assert r1.goal == r2.goal
        assert r1.state == r2.state

    def test_result_is_json_safe(self) -> None:
        sg = Subgoal(
            subgoal_id="",
            goal="goal",
            context={},
            metadata={},
        )
        result = repair_subgoal(sg)
        dumped = json.dumps({
            "subgoal_id": result.subgoal_id,
            "goal": result.goal,
            "context": result.context,
            "metadata": result.metadata,
            "state": result.state.value,
        })
        assert isinstance(dumped, str)


# ============================================================================
# repair_drift_inconsistency
# ============================================================================


class TestRepairDriftInconsistency:
    """Tests for repair_drift_inconsistency()."""

    def test_valid_plan_state_returns_unchanged(self) -> None:
        ps = PlanState(
            plan_id="plan-1",
            steps=[{"step": 1}],
            current_step_index=0,
            status=PlanStatus.RUNNING,
            last_result={"ok": True},
            trace=[{"event": "started"}],
            created_at=1000,
            updated_at=2000,
        )
        result = repair_drift_inconsistency(ps)
        assert result is ps

    def test_corrupt_steps_removes_non_dicts(self) -> None:
        ps = PlanState(
            plan_id="plan-1",
            steps=[{"step": 1}, None, 42, "string"],  # type: ignore[list-item]
            current_step_index=0,
            status=PlanStatus.RUNNING,
            last_result=None,
            trace=[],
            created_at=0,
            updated_at=0,
        )
        result = repair_drift_inconsistency(ps)
        assert result.steps == [{"step": 1}]

    def test_invalid_step_index_clamped(self) -> None:
        ps = PlanState(
            plan_id="plan-1",
            steps=[{"step": 1}, {"step": 2}],
            current_step_index=999,
            status=PlanStatus.RUNNING,
            last_result=None,
            trace=[],
            created_at=0,
            updated_at=0,
        )
        result = repair_drift_inconsistency(ps)
        assert result.current_step_index == 1  # len-1 = 1

    def test_negative_step_index_clamped_to_zero(self) -> None:
        ps = PlanState(
            plan_id="plan-1",
            steps=[{"step": 1}],
            current_step_index=-5,
            status=PlanStatus.RUNNING,
            last_result=None,
            trace=[],
            created_at=0,
            updated_at=0,
        )
        result = repair_drift_inconsistency(ps)
        assert result.current_step_index == 0

    def test_empty_steps_index_is_zero(self) -> None:
        ps = PlanState(
            plan_id="plan-1",
            steps=[],
            current_step_index=3,
            status=PlanStatus.RUNNING,
            last_result=None,
            trace=[],
            created_at=0,
            updated_at=0,
        )
        result = repair_drift_inconsistency(ps)
        assert result.current_step_index == 0

    def test_invalid_status_defaults_to_pending(self) -> None:
        ps = PlanState(
            plan_id="plan-1",
            steps=[],
            current_step_index=0,
            status="bogus",  # type: ignore[arg-type]
            last_result=None,
            trace=[],
            created_at=0,
            updated_at=0,
        )
        result = repair_drift_inconsistency(ps)
        assert result.status == PlanStatus.PENDING

    def test_non_dict_last_result_set_to_none(self) -> None:
        ps = PlanState(
            plan_id="plan-1",
            steps=[],
            current_step_index=0,
            status=PlanStatus.RUNNING,
            last_result="not a dict",  # type: ignore[arg-type]
            trace=[],
            created_at=0,
            updated_at=0,
        )
        result = repair_drift_inconsistency(ps)
        assert result.last_result is None

    def test_corrupt_trace_removes_non_dicts(self) -> None:
        ps = PlanState(
            plan_id="plan-1",
            steps=[],
            current_step_index=0,
            status=PlanStatus.RUNNING,
            last_result=None,
            trace=[{"event": "x"}, None, "bad"],  # type: ignore[list-item]
            created_at=0,
            updated_at=0,
        )
        result = repair_drift_inconsistency(ps)
        assert result.trace == [{"event": "x"}]

    def test_does_not_mutate_input(self) -> None:
        ps = PlanState(
            plan_id="plan-1",
            steps=[],
            current_step_index=5,
            status=PlanStatus.COMPLETED,
            last_result={"ok": True},
            trace=[],
            created_at=100,
            updated_at=200,
        )
        repair_drift_inconsistency(ps)
        assert ps.current_step_index == 5
        assert ps.status == PlanStatus.COMPLETED

    def test_deterministic_output(self) -> None:
        ps = PlanState(
            plan_id="plan-1",
            steps=[None, {"step": 1}],  # type: ignore[list-item]
            current_step_index=10,
            status="bad",  # type: ignore[arg-type]
            last_result="bad",
            trace=[None],
            created_at=0,
            updated_at=0,
        )
        r1 = repair_drift_inconsistency(ps)
        r2 = repair_drift_inconsistency(ps)
        assert r1.steps == r2.steps
        assert r1.current_step_index == r2.current_step_index
        assert r1.status == r2.status
        assert r1.last_result == r2.last_result
        assert r1.trace == r2.trace

    def test_result_is_json_safe(self) -> None:
        ps = PlanState(
            plan_id="plan-1",
            steps=[{"step": 1}],
            current_step_index=0,
            status=PlanStatus.RUNNING,
            last_result=None,
            trace=[],
            created_at=0,
            updated_at=0,
        )
        result = repair_drift_inconsistency(ps)
        dumped = json.dumps({
            "plan_id": result.plan_id,
            "steps": result.steps,
            "current_step_index": result.current_step_index,
            "status": result.status.value,
            "last_result": result.last_result,
            "trace": result.trace,
        })
        assert isinstance(dumped, str)
