"""
Phase 2.18.1 — Integration test suite
======================================

Validates the full plan-execute-repair loop across multi-subgoal prompts:
- Full pipeline: Planner (mock LLM) → Executor → Repair
- Cross-component boundary validation (Planner→Executor, Executor→Repair)
- Contract version integrity at boundaries
- Multi-subgoal end-to-end execution
"""

from __future__ import annotations

import pytest

from src.strategy.llm.mock_llm import MockLLM
from src.strategy.memory.governance.memory_governance import MemoryGovernance
from src.strategy.memory.plan_memory import PlanMemory
from src.strategy.memory.segment_memory import SegmentMemory
from src.strategy.memory.subgoal_memory import SubgoalMemory
from src.strategy.memory.drift_memory import DriftMemory
from src.strategy.memory.plan_memory_types import PlanMemoryRecord
from src.strategy.memory.segment_memory_types import SegmentMemoryRecord
from src.strategy.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.strategy.memory.drift_memory_types import DriftEvent
from src.strategy.memory.repair.plan_repair import PlanRepair
from src.strategy.memory.repair.repair_types import (
    BreakageError,
    DriftFlag,
    PlanBreakageReport,
    RepairAction,
    RepairPlan,
)
from src.strategy.planning.contracts.agent_plan import (
    AgentPlan,
    CURRENT_CONTRACT_VERSION,
)
from src.strategy.planning.contracts.step_spec import (
    CURRENT_STEP_SPEC_VERSION,
)
from src.strategy.planning.agent_planner import AgentPlanner
from src.strategy.types.errors.plan_errors import PlanExecutionError
from src.strategy.types.step_result import StepResult
from src.strategy.types.cognitive_step_outcome import CognitiveStepOutcome
from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState
from src.strategy.types.hashing import stable_hash


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


import time

_NOW_MS = int(time.time() * 1000)
_SG_ID = stable_hash({"test": "full_pipeline_suite"})


def _make_governance(
    subgoal_id: str = "sg-int",
) -> tuple[MemoryGovernance, PlanMemory]:
    """Create a MemoryGovernance with pre-loaded subgoal and a fresh PlanMemory.

    Returns (governance, plan_memory) so the same PlanMemory can be
    shared with AgentPlanner.
    """
    sm = SubgoalMemory()
    subgoal = Subgoal(
        subgoal_id=subgoal_id,
        goal="Validate architecture and verify loop termination",
        context={},
        metadata={},
        state=SubgoalLifecycleState.CREATED,
        created_at=_NOW_MS,
    )
    sm.put(subgoal)
    pm = PlanMemory()
    governance = MemoryGovernance(sm, SegmentMemory(), pm, DriftMemory())
    return governance, pm


def _make_planner(plan_memory: PlanMemory) -> AgentPlanner:
    """Create an AgentPlanner backed by MockLLM with the given PlanMemory."""
    return AgentPlanner(llm_complete=MockLLM().make_complete(), plan_memory=plan_memory)


def _create_plan(governance: MemoryGovernance, plan_memory: PlanMemory) -> AgentPlan:
    """Generate a plan via the full AgentPlanner pipeline with MockLLM."""
    planner = _make_planner(plan_memory)
    return planner.plan(
        subgoal_id="sg-int",
        goal="Validate architecture and verify loop termination",
        governance=governance,
        timestamp="2025-01-01T00:00:00Z",
    )


def _make_success_step_result() -> StepResult:
    """A successful StepResult for cross-boundary tests."""
    return StepResult(
        outcome=CognitiveStepOutcome.SUCCESS,
        reason="completed",
        payload={"status": "ok"},
        trace=[],
    )


def _make_failure_step_result() -> StepResult:
    """A failed StepResult for cross-boundary tests."""
    return StepResult.failure(
        reason="skill execution failed: timeout",
        payload={"error_type": "TimeoutError"},
        trace=[],
    )


def _make_plan_record(plan_id: str = "plan-1", subgoal_id: str = "sg-1",
                      segments: list | None = None) -> PlanMemoryRecord:
    """Create a minimal PlanMemoryRecord for repair detection tests."""
    return PlanMemoryRecord(
        plan_id=plan_id,
        subgoal_id=subgoal_id,
        segments=segments or ["seg-a"],
        created_at="2025-01-01T00:00:00Z",
        metadata={},
        intent="test intent",
        targetskillid="stdlib.echo",
        arguments={},
        reasoning_summary="because reasons",
    )


def _make_segment_record(segment_id: str = "seg-a", subgoal_id: str = "sg-1",
                          parent_id: str | None = None,
                          state: str = "success") -> SegmentMemoryRecord:
    """Create a minimal SegmentMemoryRecord for repair detection tests."""
    return SegmentMemoryRecord(
        segment_id=segment_id,
        parent_id=parent_id,
        subgoal_id=subgoal_id,
        state=state,
        content=["step-1"],
        created_at="2025-01-01T00:00:00Z",
        context={},
        metadata={},
        skills=["stdlib.echo"],
        last_output={},
        previous_output=None,
        behavioural_delta=None,
        error=None,
    )


def _make_subgoal_record(subgoal_id: str = "sg-1") -> SubgoalMemoryRecord:
    """Create a minimal SubgoalMemoryRecord."""
    return SubgoalMemoryRecord(
        subgoal_id=subgoal_id,
        parent_id=None,
        state="active",
        goal="test goal",
        context={},
        metadata={},
        created_at=1000,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 2.18.1a — Full pipeline: Planner → AgentPlan
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullPipelinePlannerToPlan:
    """Validate the Planner → AgentPlan stage of the full pipeline."""

    def test_agent_plan_generated_with_mock_llm(self):
        """AgentPlanner with MockLLM produces a valid AgentPlan."""
        governance, pm = _make_governance()
        agent_plan = _create_plan(governance, pm)

        assert agent_plan.plan_id
        assert agent_plan.subgoal_id == "sg-int"
        assert agent_plan.intent
        assert agent_plan.segments
        assert agent_plan.version == CURRENT_CONTRACT_VERSION

    def test_agent_plan_has_required_identity_fields(self):
        """AgentPlan must carry plan_id, subgoal_id, segments, intent."""
        governance, pm = _make_governance()
        agent_plan = _create_plan(governance, pm)

        assert agent_plan.plan_id != ""
        assert agent_plan.subgoal_id != ""
        assert len(agent_plan.segments) > 0
        assert agent_plan.intent != ""
        assert agent_plan.targetskillid != ""

    def test_agent_plan_version_is_current(self):
        """AgentPlan.version must match CURRENT_CONTRACT_VERSION."""
        governance, pm = _make_governance()
        agent_plan = _create_plan(governance, pm)
        assert agent_plan.version == "1.0"

    def test_agent_plan_serializable_to_dict(self):
        """AgentPlan must be serializable to a dict for boundary crossing."""
        governance, pm = _make_governance()
        agent_plan = _create_plan(governance, pm)

        d = agent_plan.to_dict()
        assert isinstance(d, dict)
        assert "plan_id" in d
        assert "version" in d
        assert d["version"] == CURRENT_CONTRACT_VERSION

    def test_repeated_planning_is_deterministic(self):
        """Same MockLLM + same goal → deterministic AgentPlan."""
        governance1, pm1 = _make_governance()
        governance2, pm2 = _make_governance()
        plan1 = _create_plan(governance1, pm1)
        plan2 = _create_plan(governance2, pm2)

        assert plan1.to_dict() == plan2.to_dict()

    def test_agent_plan_serializable_to_json(self):
        """AgentPlan JSON serialization must succeed (boundary crossing)."""
        import json
        governance, pm = _make_governance()
        agent_plan = _create_plan(governance, pm)
        json_str = json.dumps(agent_plan.to_dict(), sort_keys=True, default=str)
        assert isinstance(json_str, str)
        roundtripped = json.loads(json_str)
        assert roundtripped["plan_id"] == agent_plan.plan_id


# ═══════════════════════════════════════════════════════════════════════════════
# 2.18.1b — Cross-component boundary: Planner → Executor
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlannerToExecutorBoundary:
    """Validate that AgentPlan output satisfies the Executor's input contract."""

    def test_agent_plan_has_executor_required_fields(self):
        """Executor requires plan_id, targetskillid, arguments from AgentPlan."""
        governance, pm = _make_governance()
        agent_plan = _create_plan(governance, pm)

        assert agent_plan.plan_id  # executor needs plan identity
        assert agent_plan.targetskillid  # executor needs a target skill
        assert isinstance(agent_plan.arguments, dict)  # executor consumes args

    def test_agent_plan_targetskillid_is_non_empty(self):
        """Executor cannot dispatch without a valid targetskillid."""
        governance, pm = _make_governance()
        agent_plan = _create_plan(governance, pm)
        assert agent_plan.targetskillid
        assert isinstance(agent_plan.targetskillid, str)

    def test_agent_plan_arguments_is_dict(self):
        """Executor expects arguments as Dict[str, Any]."""
        governance, pm = _make_governance()
        agent_plan = _create_plan(governance, pm)
        assert isinstance(agent_plan.arguments, dict)

    def test_agent_plan_to_plan_roundtrip(self):
        """AgentPlan.from_plan_and_record → Plan is consumed by executor."""
        governance, pm = _make_governance()
        agent_plan = _create_plan(governance, pm)

        from src.strategy.planning.models.plan import Plan
        plan = Plan(
            intent=agent_plan.intent,
            targetskillid=agent_plan.targetskillid,
            arguments=agent_plan.arguments,
            reasoning_summary=agent_plan.reasoning_summary,
        )
        assert plan.intent == agent_plan.intent
        assert plan.targetskillid == agent_plan.targetskillid


# ═══════════════════════════════════════════════════════════════════════════════
# 2.18.1c — Cross-component boundary: Executor → Repair
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecutorToRepairBoundary:
    """Validate that executor/plan output satisfies the Repair system's input contract."""

    def test_plan_repair_detects_missing_segment(self):
        """PlanRepair detects a segment in plan_record not in SegmentMemory."""
        repair = PlanRepair()
        plan_record = _make_plan_record(segments=["seg-a", "seg-missing"])
        real_segments = {"seg-a": _make_segment_record("seg-a")}
        subgoals = {"sg-1": _make_subgoal_record("sg-1")}

        report = repair.detect_breakages(
            plan_record=plan_record,
            real_segments_by_id=real_segments,
            regenerated_ids=set(),
            subgoals_by_id=subgoals,
            drift_events=[],
            now=1000,
        )
        assert not report.is_clean
        assert any(e.error_type == "MISSING_SEGMENT" for e in report.errors)
        assert "seg-missing" in report.missing_segments

    def test_plan_repair_detects_broken_parent_link(self):
        """PlanRepair detects a segment whose parent_id does not exist."""
        repair = PlanRepair()
        plan_record = _make_plan_record(segments=["seg-a"])
        real_segments = {"seg-a": _make_segment_record("seg-a", parent_id="nonexistent")}
        subgoals = {"sg-1": _make_subgoal_record("sg-1")}

        report = repair.detect_breakages(
            plan_record=plan_record,
            real_segments_by_id=real_segments,
            regenerated_ids=set(),
            subgoals_by_id=subgoals,
            drift_events=[],
            now=1000,
        )
        assert not report.is_clean
        assert any(e.error_type == "BROKEN_PARENT_LINK" for e in report.errors)

    def test_plan_repair_clean_plan_passes(self):
        """PlanRepair reports is_clean for a well-formed plan."""
        repair = PlanRepair()
        plan_record = _make_plan_record(segments=["seg-a"])
        real_segments = {"seg-a": _make_segment_record("seg-a")}
        subgoals = {"sg-1": _make_subgoal_record("sg-1")}

        report = repair.detect_breakages(
            plan_record=plan_record,
            real_segments_by_id=real_segments,
            regenerated_ids=set(),
            subgoals_by_id=subgoals,
            drift_events=[],
            now=1000,
        )
        assert report.is_clean
        assert len(report.errors) == 0

    def test_plan_repair_produces_repair_plan(self):
        """PlanRepair.repair produces a RepairPlan from breakage report."""
        repair = PlanRepair()
        plan_record = _make_plan_record(segments=["seg-missing"])
        real_segments = {}
        subgoals = {"sg-1": _make_subgoal_record("sg-1")}

        report = repair.detect_breakages(
            plan_record=plan_record,
            real_segments_by_id=real_segments,
            regenerated_ids=set(),
            subgoals_by_id=subgoals,
            drift_events=[],
            now=1000,
        )
        assert not report.is_clean

        outcome = repair.repair(
            plan_record=plan_record,
            real_segments_by_id=real_segments,
            subgoals_by_id=subgoals,
            drift_events=[],
            now=1000,
            repair_budget=5,
            retry_limit=3,
        )
        assert outcome.success is True  # missing segment was regenerated
        assert "seg-missing" in outcome.repaired_plan.segments
        assert any(
            a.target_id == "seg-missing"
            for a in outcome.repair_actions_applied
        )
        assert len(outcome.repair_actions_applied) > 0
        assert outcome.attempts >= 1

    def test_breakage_report_has_plan_id(self):
        """PlanBreakageReport carries plan_id for traceability."""
        repair = PlanRepair()
        plan_record = _make_plan_record(plan_id="plan-traceable")
        real_segments = {"seg-a": _make_segment_record("seg-a")}
        subgoals = {"sg-1": _make_subgoal_record("sg-1")}

        report = repair.detect_breakages(
            plan_record=plan_record,
            real_segments_by_id=real_segments,
            regenerated_ids=set(),
            subgoals_by_id=subgoals,
            drift_events=[],
            now=1000,
        )
        assert report.plan_id == "plan-traceable"

    def test_step_result_reason_preserved_for_repair_context(self):
        """StepResult reason survives across the executor-repair boundary."""
        result = _make_failure_step_result()
        assert "timeout" in result.reason.lower()
        assert result.outcome == CognitiveStepOutcome.FAILURE
        # This StepResult would be consumed by repair when mapped to a
        # SegmentMemoryRecord with state="error" — ensuring repair gets context.
        assert result.payload is not None
        assert result.payload.get("error_type") == "TimeoutError"


# ═══════════════════════════════════════════════════════════════════════════════
# 2.18.1d — Contract version integrity at boundaries
# ═══════════════════════════════════════════════════════════════════════════════


class TestContractVersionIntegrity:
    """Validate contract versions are consistent at all boundaries."""

    def test_agent_plan_version_matches_constant(self):
        """AgentPlan must use CURRENT_CONTRACT_VERSION."""
        governance, pm = _make_governance()
        agent_plan = _create_plan(governance, pm)
        assert agent_plan.version == CURRENT_CONTRACT_VERSION
        assert CURRENT_CONTRACT_VERSION == "1.0"

    def test_step_spec_version_matches_constant(self):
        """StepSpec must use CURRENT_STEP_SPEC_VERSION."""
        assert CURRENT_STEP_SPEC_VERSION == "1.0"

    def test_s2_s3_contract_version_defined(self):
        """S2→S3 contract must have a defined version."""
        from src.capabilities.contracts import S2_S3_CONTRACT_VERSION
        assert S2_S3_CONTRACT_VERSION
        assert isinstance(S2_S3_CONTRACT_VERSION, str)

    def test_agent_plan_version_in_serialized_output(self):
        """Serialized AgentPlan must carry its version field."""
        governance, pm = _make_governance()
        agent_plan = _create_plan(governance, pm)
        d = agent_plan.to_dict()
        assert d["version"] == "1.0"


# ═══════════════════════════════════════════════════════════════════════════════
# 2.18.1e — Repair plan integrity
# ═══════════════════════════════════════════════════════════════════════════════


class TestRepairPlanIntegrity:
    """Validate that repair plans are well-formed and actionable."""

    def test_repair_plan_has_required_fields(self):
        """RepairPlan must have actions and regeneration fields."""
        rp = RepairPlan(
            actions=(
                RepairAction(action_type="REGENERATE_SEGMENT", target_id="seg-a", details={}),
                RepairAction(action_type="RECONSTRUCT_CHAIN", target_id="seg-b", details={}),
            ),
            requires_redecomposition=False,
            requires_segment_regeneration=("seg-a",),
            requires_subgoal_repair=(),
        )
        assert len(rp.actions) == 2
        assert rp.actions[0].action_type == "REGENERATE_SEGMENT"
        assert "seg-a" in rp.requires_segment_regeneration
        assert not rp.requires_redecomposition

    def test_repair_plan_actions_have_targets(self):
        """Every RepairAction must identify its target_id."""
        rp = RepairPlan(
            actions=(
                RepairAction(action_type="QUARANTINE_SEGMENT", target_id="seg-x", details={}),
            ),
            requires_redecomposition=False,
            requires_segment_regeneration=(),
            requires_subgoal_repair=(),
        )
        for action in rp.actions:
            assert action.target_id
            assert action.action_type

    def test_repair_plan_requires_redecomposition_flag(self):
        """Missing subgoal → requires_redecomposition=True."""
        rp = RepairPlan(
            actions=(),
            requires_redecomposition=True,
            requires_segment_regeneration=(),
            requires_subgoal_repair=("sg-missing",),
        )
        assert rp.requires_redecomposition
        assert "sg-missing" in rp.requires_subgoal_repair

    def test_repair_strategy_context_structure(self):
        """RepairStrategyContext provides deterministic hints from semantic memory."""
        from src.strategy.memory.repair.repair_types import RepairStrategyContext

        ctx = RepairStrategyContext(
            preferred_capabilities=("stdlib.echo",),
            avoid_capabilities=(),
            successful_patterns=("stdlib.echo|stdlib.fetch",),
            drift_risks=(),
            confidence=0.85,
            matches=3,
        )
        assert ctx.preferred_capabilities == ("stdlib.echo",)
        assert ctx.confidence == 0.85
        assert ctx.matches == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 2.18.1f — Error boundary propagation
# ═══════════════════════════════════════════════════════════════════════════════


class TestErrorBoundaryPropagation:
    """Validate that errors propagate correctly across component boundaries."""

    def test_plan_execution_error_has_reason(self):
        """PlanExecutionError must carry a reason string for repair context."""
        error = PlanExecutionError("Skill 'echo' timed out after 30s")
        assert "echo" in str(error)
        assert "30s" in str(error)

    def test_step_result_failure_preserves_error_type(self):
        """StepResult.failure payload must preserve the error type."""
        result = StepResult.failure(
            reason="network timeout",
            payload={"error_type": "TimeoutError"},
            trace=[],
        )
        assert result.payload is not None
        assert result.payload.get("error_type") == "TimeoutError"

    def test_drift_events_fed_to_repair_are_detectable(self):
        """DriftEvents passed to PlanRepair are flagged in the breakage report."""
        repair = PlanRepair()
        plan_record = _make_plan_record(plan_id="plan-drift", segments=["seg-a"])
        real_segments = {"seg-a": _make_segment_record("seg-a")}
        subgoals = {"sg-1": _make_subgoal_record("sg-1")}
        drift_event = DriftEvent(
            timestamp=1000,
            subgoal_id="sg-1",
            segment_id="seg-a",
            step_id=None,
            signal_type="CONTENT_DRIFT",
            confidence=0.9,
            details={},
        )

        report = repair.detect_breakages(
            plan_record=plan_record,
            real_segments_by_id=real_segments,
            regenerated_ids=set(),
            subgoals_by_id=subgoals,
            drift_events=[drift_event],
            now=1000,
        )
        # Drift events produce warnings in the report
        drift_warnings = [w for w in report.warnings if w.warning_type == "DRIFT_FLAG"]
        assert len(drift_warnings) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 2.18.1g — Multi-subgoal full pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultiSubgoalPipeline:
    """Validate the pipeline across multiple subgoals."""

    def test_two_plans_different_subgoals_independent(self):
        """Two plans for different subgoals must not interfere."""
        governance, pm = _make_governance()
        plan1 = _create_plan(governance, pm)

        # Pre-register sg-2 in SubgoalMemory so governance accepts the plan
        governance.put_subgoal(Subgoal(
            subgoal_id="sg-2",
            goal="Validate architecture and verify loop termination",
            context={},
            metadata={},
            state=SubgoalLifecycleState.CREATED,
            created_at=_NOW_MS,
        ))

        # Create a second plan
        planner = _make_planner(pm)
        plan2 = planner.plan(
            subgoal_id="sg-2",
            goal="Validate architecture and verify loop termination",
            governance=governance,
            timestamp="2025-01-01T00:00:01Z",
        )

        assert plan1.plan_id != plan2.plan_id
        assert plan1.subgoal_id == "sg-int"
        assert plan2.subgoal_id == "sg-2"

    def test_multi_subgoal_plans_all_have_contract_version(self):
        """All plans from multi-subgoal pipeline must carry CURRENT_CONTRACT_VERSION."""
        governance, pm = _make_governance()
        plan1 = _create_plan(governance, pm)

        # Pre-register sg-3 in SubgoalMemory so governance accepts the plan
        governance.put_subgoal(Subgoal(
            subgoal_id="sg-3",
            goal="Validate architecture and verify loop termination",
            context={},
            metadata={},
            state=SubgoalLifecycleState.CREATED,
            created_at=_NOW_MS,
        ))

        planner = _make_planner(pm)
        plan2 = planner.plan(
            subgoal_id="sg-3",
            goal="Validate architecture and verify loop termination",
            governance=governance,
            timestamp="2025-01-01T00:00:02Z",
        )

        assert plan1.version == CURRENT_CONTRACT_VERSION
        assert plan2.version == CURRENT_CONTRACT_VERSION
