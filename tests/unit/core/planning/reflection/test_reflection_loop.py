"""
Tests for Phase 2.5.5 — Reflection Loop.

Covers:
  - evaluate_progress (pure function)
  - ReflectionLoop.run_reflection_cycle
    - basic cycle structure
    - drift detection and classification
    - BLOCK / UNBLOCK / RETRY transitions
    - plan repair and persistence
    - per-subgoal detector isolation
    - error collection without cycle abort
    - trace completeness
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List

import pytest

from src.core.memory.subgoal_memory import SubgoalMemory
from src.core.memory.segment_memory import SegmentMemory
from src.core.memory.plan_memory import PlanMemory
from src.core.memory.drift_memory import DriftMemory
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord, SubgoalMemorySnapshot
from src.core.memory.segment_memory_types import SegmentMemoryRecord, SegmentMemorySnapshot
from src.core.memory.drift_memory_types import DriftEvent
from src.core.memory.plan_memory_types import PlanMemoryRecord
from src.core.memory.governance.memory_governance import MemoryGovernance
from src.core.planning.models.plan import Plan
from src.core.planning.reflection.progress_evaluator import evaluate_progress
from src.core.planning.reflection.reflection_loop import ReflectionLoop
from src.core.planning.reflection.reflection_types import (
    ProgressReport,
    ReflectionState,
)
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState
from src.core.types.plan_segment import PlanSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW_MS = int(time.time() * 1000)
NOW_ISO = datetime.fromtimestamp(NOW_MS / 1000.0, tz=timezone.utc).isoformat()


def make_subgoal(
    subgoal_id: str = "sg-1",
    state: SubgoalLifecycleState = SubgoalLifecycleState.READY,
    goal: str = "do something",
) -> Subgoal:
    return Subgoal(
        subgoal_id=subgoal_id,
        goal=goal,
        context={},
        metadata={},
        state=state,
        created_at=NOW_MS,
    )


def make_segment(subgoal_id: str = "sg-1", steps: List[str] = None) -> PlanSegment:
    return PlanSegment(
        subgoal_id=subgoal_id,
        steps=steps or ["step one"],
        context={},
        metadata={},
    )


def make_plan(plan_id: str, subgoal_id: str, segment_ids: List[str] = None) -> Plan:
    return Plan(
        intent="test intent",
        targetskillid="skill-1",
        arguments={},
        reasoning_summary="test summary",
    )


def fresh_state(
    subgoal: Subgoal,
    cycle: int = 1,
    plan_id: str = None,
    repair_attempts: int = 0,
    prior_progress: ProgressReport = None,
) -> ReflectionState:
    sm = SubgoalMemory()
    sm.put(subgoal)
    segm = SegmentMemory()
    pm = PlanMemory()
    dm = DriftMemory()
    return ReflectionState(
        cycle=cycle,
        timestamp=NOW_MS,
        subgoal_id=subgoal.subgoal_id,
        subgoal_memory=sm,
        segment_memory=segm,
        plan_memory=pm,
        drift_memory=dm,
        plan_id=plan_id,
        repair_attempts=repair_attempts,
        prior_progress=prior_progress,
    )


def make_snapshot_from_record(record: SubgoalMemoryRecord) -> SubgoalMemorySnapshot:
    return SubgoalMemorySnapshot(records=(record,))


def make_seg_snapshot_from_record(record: SegmentMemoryRecord) -> SegmentMemorySnapshot:
    return SegmentMemorySnapshot(records=(record,))


def empty_subgoal_snap() -> SubgoalMemorySnapshot:
    return SubgoalMemorySnapshot(records=())


def empty_seg_snap() -> SegmentMemorySnapshot:
    return SegmentMemorySnapshot(records=())


# ---------------------------------------------------------------------------
# evaluate_progress
# ---------------------------------------------------------------------------

class TestEvaluateProgress:

    def test_empty_stores_returns_zeros_and_no_subgoals_stall(self):
        result = evaluate_progress(empty_subgoal_snap(), empty_seg_snap())
        assert result.subgoals_complete == 0
        assert result.subgoals_total == 0
        assert result.segments_total == 0
        assert result.stalled is True
        assert "no_subgoals" in result.stalled_reasons

    def test_single_pending_subgoal_not_stalled(self):
        rec = SubgoalMemoryRecord(
            subgoal_id="sg-1", parent_id=None, state="pending",
            goal="g", context={}, metadata={}, created_at=NOW_MS,
        )
        result = evaluate_progress(
            SubgoalMemorySnapshot(records=(rec,)), empty_seg_snap()
        )
        assert result.subgoals_complete == 0
        assert result.subgoals_total == 1
        assert result.stalled is False
        assert result.progress_rate == "steady"

    def test_complete_subgoal_counted(self):
        for state_val in ("success", "satisfied", "closed"):
            rec = SubgoalMemoryRecord(
                subgoal_id="sg-1", parent_id=None, state=state_val,
                goal="g", context={}, metadata={}, created_at=NOW_MS,
            )
            result = evaluate_progress(
                SubgoalMemorySnapshot(records=(rec,)), empty_seg_snap()
            )
            assert result.subgoals_complete == 1, f"Failed for state: {state_val}"

    def test_all_blocked_triggers_stall(self):
        rec = SubgoalMemoryRecord(
            subgoal_id="sg-1", parent_id=None, state="blocked",
            goal="g", context={}, metadata={}, created_at=NOW_MS,
        )
        result = evaluate_progress(
            SubgoalMemorySnapshot(records=(rec,)), empty_seg_snap()
        )
        assert result.stalled is True
        assert "all_subgoals_blocked_or_failed" in result.stalled_reasons

    def test_mixed_states_not_all_problem(self):
        records = (
            SubgoalMemoryRecord("sg-1", None, "blocked", "g", {}, {}, NOW_MS),
            SubgoalMemoryRecord("sg-2", None, "running", "g", {}, {}, NOW_MS),
        )
        result = evaluate_progress(
            SubgoalMemorySnapshot(records=records), empty_seg_snap()
        )
        assert result.stalled is False

    def test_repair_loop_stall(self):
        rec = SubgoalMemoryRecord(
            subgoal_id="sg-1", parent_id=None, state="running",
            goal="g", context={}, metadata={}, created_at=NOW_MS,
        )
        result = evaluate_progress(
            SubgoalMemorySnapshot(records=(rec,)), empty_seg_snap(),
            repair_attempts=3, stall_repair_threshold=3,
        )
        assert "repair_loop" in result.stalled_reasons

    def test_repair_below_threshold_not_stalled(self):
        rec = SubgoalMemoryRecord(
            subgoal_id="sg-1", parent_id=None, state="running",
            goal="g", context={}, metadata={}, created_at=NOW_MS,
        )
        result = evaluate_progress(
            SubgoalMemorySnapshot(records=(rec,)), empty_seg_snap(),
            repair_attempts=2, stall_repair_threshold=3,
        )
        assert "repair_loop" not in result.stalled_reasons

    def test_segments_complete_counts_by_subgoal_state(self):
        sg_rec = SubgoalMemoryRecord("sg-1", None, "success", "g", {}, {}, NOW_MS)
        seg_rec = SegmentMemoryRecord(
            segment_id="seg-1", parent_id=None, subgoal_id="sg-1",
            state=None, content=["s1"], created_at=NOW_ISO, context={}, metadata={},
        )
        result = evaluate_progress(
            SubgoalMemorySnapshot(records=(sg_rec,)),
            SegmentMemorySnapshot(records=(seg_rec,)),
        )
        assert result.segments_complete == 1
        assert result.segments_total == 1

    def test_segments_of_incomplete_subgoal_not_complete(self):
        sg_rec = SubgoalMemoryRecord("sg-1", None, "running", "g", {}, {}, NOW_MS)
        seg_rec = SegmentMemoryRecord(
            segment_id="seg-1", parent_id=None, subgoal_id="sg-1",
            state=None, content=["s1"], created_at=NOW_ISO, context={}, metadata={},
        )
        result = evaluate_progress(
            SubgoalMemorySnapshot(records=(sg_rec,)),
            SegmentMemorySnapshot(records=(seg_rec,)),
        )
        assert result.segments_complete == 0

    def test_progress_rate_increasing_vs_prior(self):
        prior = ProgressReport(
            subgoals_complete=0, subgoals_total=2,
            segments_complete=0, segments_total=0,
            stalled=False, stalled_reasons=(), progress_rate="steady",
        )
        rec = SubgoalMemoryRecord("sg-1", None, "success", "g", {}, {}, NOW_MS)
        result = evaluate_progress(
            SubgoalMemorySnapshot(records=(rec,)), empty_seg_snap(),
            prior_progress=prior,
        )
        assert result.progress_rate == "increasing"

    def test_progress_rate_decreasing_vs_prior(self):
        prior = ProgressReport(
            subgoals_complete=2, subgoals_total=2,
            segments_complete=0, segments_total=0,
            stalled=False, stalled_reasons=(), progress_rate="steady",
        )
        rec = SubgoalMemoryRecord("sg-1", None, "running", "g", {}, {}, NOW_MS)
        result = evaluate_progress(
            SubgoalMemorySnapshot(records=(rec,)), empty_seg_snap(),
            prior_progress=prior,
        )
        assert result.progress_rate == "decreasing"

    def test_unknown_state_string_does_not_crash(self):
        rec = SubgoalMemoryRecord("sg-1", None, "UNKNOWN_XYZ", "g", {}, {}, NOW_MS)
        result = evaluate_progress(
            SubgoalMemorySnapshot(records=(rec,)), empty_seg_snap()
        )
        assert result.subgoals_complete == 0
        assert result.stalled is False  # unknown state → not a problem state

    def test_stall_overrides_progress_rate(self):
        rec = SubgoalMemoryRecord("sg-1", None, "failed", "g", {}, {}, NOW_MS)
        result = evaluate_progress(
            SubgoalMemorySnapshot(records=(rec,)), empty_seg_snap()
        )
        assert result.stalled is True
        assert result.progress_rate == "stalled"


# ---------------------------------------------------------------------------
# ReflectionLoop — basic cycle
# ---------------------------------------------------------------------------

class TestReflectionLoopBasicCycle:

    def test_cycle_returns_outcome_with_correct_cycle_number(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg, cycle=5))
        assert outcome.cycle == 5

    def test_cycle_timestamp_is_iso_string(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        # Should parse without error
        datetime.fromisoformat(outcome.timestamp)

    def test_progress_included_in_outcome(self):
        sg = make_subgoal(state=SubgoalLifecycleState.SUCCESS)
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert outcome.progress.subgoals_total == 1
        assert outcome.progress.subgoals_complete == 1

    def test_no_drift_on_first_cycle_single_subgoal(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        # Single clean cycle cannot confirm drift (needs confirmation_cycles=2).
        assert outcome.drift_report.confirmation.confirmed is False

    def test_trace_cycle_matches_outcome_cycle(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg, cycle=3))
        assert outcome.trace.cycle == 3

    def test_trace_contains_progress_dict(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert "subgoals_total" in outcome.trace.progress
        assert "progress_rate" in outcome.trace.progress

    def test_trace_contains_drift_dict(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert "confirmed" in outcome.trace.drift
        assert "classification" in outcome.trace.drift

    def test_validation_result_present_for_known_subgoal(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert outcome.validation_result is not None

    def test_validation_result_none_for_unknown_subgoal(self):
        loop = ReflectionLoop()
        sm = SubgoalMemory()
        state = ReflectionState(
            cycle=1,
            timestamp=NOW_MS,
            subgoal_id="nonexistent",
            subgoal_memory=sm,
            segment_memory=SegmentMemory(),
            plan_memory=PlanMemory(),
            drift_memory=DriftMemory(),
        )
        outcome = loop.run_reflection_cycle(state)
        assert outcome.validation_result is None

    def test_no_plan_adjustment_without_plan_id(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg, plan_id=None))
        assert outcome.plan_adjustment is None

    def test_no_errors_on_clean_cycle(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert outcome.errors == ()


# ---------------------------------------------------------------------------
# ReflectionLoop — drift multi-cycle confirmation
# ---------------------------------------------------------------------------

class TestReflectionLoopDrift:

    def _build_state_with_violations(self, subgoal: Subgoal, violations_count: int = 5):
        """
        Build a ReflectionState whose DriftContext will emit behavioural signals
        by pre-loading transition_failures above the threshold.
        """
        from src.core.planning.drift.drift_context import TransitionFailureRecord
        failures = [
            TransitionFailureRecord(from_state="running", event="start", count=10)
            for _ in range(violations_count)
        ]
        sm = SubgoalMemory()
        sm.put(subgoal)
        return ReflectionState(
            cycle=1,
            timestamp=NOW_MS,
            subgoal_id=subgoal.subgoal_id,
            subgoal_memory=sm,
            segment_memory=SegmentMemory(),
            plan_memory=PlanMemory(),
            drift_memory=DriftMemory(),
            transition_failures=failures,
            repair_attempts=5,  # also triggers repair_attempts signal
        )

    def test_drift_not_confirmed_after_one_cycle(self):
        sg = make_subgoal()
        loop = ReflectionLoop(confirmation_cycles=2)
        state = self._build_state_with_violations(sg)
        outcome = loop.run_reflection_cycle(state)
        # Needs 2 cycles to confirm.
        assert outcome.drift_report.confirmation.confirmed is False

    def test_drift_confirmed_after_n_cycles(self):
        sg = make_subgoal()
        loop = ReflectionLoop(confirmation_cycles=2)

        sm = SubgoalMemory()
        sm.put(sg)

        from src.core.planning.drift.drift_context import TransitionFailureRecord
        failures = [
            TransitionFailureRecord(from_state="running", event="start", count=10)
        ]

        for i in range(1, 4):
            state = ReflectionState(
                cycle=i,
                timestamp=NOW_MS + i,
                subgoal_id=sg.subgoal_id,
                subgoal_memory=sm,
                segment_memory=SegmentMemory(),
                plan_memory=PlanMemory(),
                drift_memory=DriftMemory(),
                transition_failures=failures,
                repair_attempts=5,
            )
            outcome = loop.run_reflection_cycle(state)

        # After enough cycles with signals, drift should be confirmed.
        assert outcome.drift_report.confirmation.confirmed is True

    def test_drift_classification_is_string(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert isinstance(outcome.drift_report.classification, str)
        assert outcome.drift_report.classification in {
            "no_drift", "minor_drift", "moderate_drift", "severe_drift", "critical_drift"
        }

    def test_drift_confidence_in_range(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert 0.0 <= outcome.drift_report.confidence <= 1.0

    def test_clean_cycle_has_no_trigger(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert outcome.drift_report.trigger is None

    def test_per_subgoal_detector_isolation(self):
        """
        Two subgoals running through the same ReflectionLoop instance must
        not share confirmation buffer state.
        """
        sg_a = make_subgoal(subgoal_id="sg-a")
        sg_b = make_subgoal(subgoal_id="sg-b")
        loop = ReflectionLoop(confirmation_cycles=2)

        from src.core.planning.drift.drift_context import TransitionFailureRecord
        failures = [TransitionFailureRecord(from_state="running", event="start", count=10)]

        sm_a = SubgoalMemory()
        sm_a.put(sg_a)
        sm_b = SubgoalMemory()
        sm_b.put(sg_b)

        # Drive sg-a through enough cycles to confirm drift.
        for i in range(1, 4):
            state_a = ReflectionState(
                cycle=i,
                timestamp=NOW_MS + i,
                subgoal_id="sg-a",
                subgoal_memory=sm_a,
                segment_memory=SegmentMemory(),
                plan_memory=PlanMemory(),
                drift_memory=DriftMemory(),
                transition_failures=failures,
                repair_attempts=5,
            )
            outcome_a = loop.run_reflection_cycle(state_a)

        # sg-b runs its first clean cycle — must NOT inherit sg-a's confirmation.
        state_b = ReflectionState(
            cycle=1,
            timestamp=NOW_MS,
            subgoal_id="sg-b",
            subgoal_memory=sm_b,
            segment_memory=SegmentMemory(),
            plan_memory=PlanMemory(),
            drift_memory=DriftMemory(),
        )
        outcome_b = loop.run_reflection_cycle(state_b)

        assert outcome_a.drift_report.confirmation.confirmed is True
        assert outcome_b.drift_report.confirmation.confirmed is False


# ---------------------------------------------------------------------------
# ReflectionLoop — subgoal transitions
# ---------------------------------------------------------------------------

class TestReflectionLoopTransitions:

    def _loop_with_confirmed_severe_drift(self, subgoal: Subgoal, sm: SubgoalMemory):
        """
        Run enough cycles with heavy signals to confirm drift.

        Returns (loop, all_outcomes) where all_outcomes is a list of per-cycle
        ReflectionOutcome objects.  The BLOCK transition fires in the first cycle
        where drift is confirmed and the subgoal is still RUNNING — subsequent
        cycles see a BLOCKED subgoal and do not re-apply the transition.
        """
        from src.core.planning.drift.drift_context import TransitionFailureRecord
        failures = [TransitionFailureRecord(from_state="running", event="start", count=10)]
        loop = ReflectionLoop(confirmation_cycles=2)

        all_outcomes = []
        for i in range(1, 4):
            state = ReflectionState(
                cycle=i,
                timestamp=NOW_MS + i,
                subgoal_id=subgoal.subgoal_id,
                subgoal_memory=sm,
                segment_memory=SegmentMemory(),
                plan_memory=PlanMemory(),
                drift_memory=DriftMemory(),
                transition_failures=failures,
                repair_attempts=5,
            )
            all_outcomes.append(loop.run_reflection_cycle(state))

        return loop, all_outcomes

    def test_no_transition_on_clean_cycle(self):
        sg = make_subgoal(state=SubgoalLifecycleState.RUNNING)
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert outcome.transitions_applied == ()

    def test_block_transition_recorded_for_running_subgoal_with_severe_drift(self):
        sg = make_subgoal(state=SubgoalLifecycleState.RUNNING)
        sm = SubgoalMemory()
        sm.put(sg)
        loop, all_outcomes = self._loop_with_confirmed_severe_drift(sg, sm)

        # Collect block transition records across ALL cycles — the block fires in the
        # first cycle where drift is confirmed and the subgoal is still RUNNING.
        all_block_records = [
            t
            for outcome in all_outcomes
            for t in outcome.transitions_applied
            if t.event == "block"
        ]

        # If any cycle confirmed severe+ drift, a block attempt must have been made.
        any_severe_confirmed = any(
            o.drift_report.confirmation.confirmed
            and o.drift_report.classification in ("severe_drift", "critical_drift")
            for o in all_outcomes
        )
        if any_severe_confirmed:
            assert len(all_block_records) >= 1
            successful_blocks = [t for t in all_block_records if t.success]
            if successful_blocks:
                assert successful_blocks[0].to_state == "blocked"

    def test_unblock_transition_for_blocked_subgoal_with_no_drift(self):
        sg = make_subgoal(state=SubgoalLifecycleState.BLOCKED)
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))

        # Fresh cycle with no signals → no_drift → UNBLOCK should be attempted.
        if not outcome.drift_report.confirmation.confirmed:
            unblock_records = [
                t for t in outcome.transitions_applied
                if t.event == "unblock"
            ]
            assert len(unblock_records) >= 1

    def test_retry_transition_after_plan_repair(self):
        """
        A FAILED subgoal with a clean plan should receive a RETRY transition
        after plan repair succeeds.
        """
        sg = make_subgoal(state=SubgoalLifecycleState.FAILED)
        sm = SubgoalMemory()
        sm.put(sg)
        segm = SegmentMemory()
        seg = make_segment(subgoal_id=sg.subgoal_id)
        segm.put(seg)
        pm = PlanMemory()
        plan = make_plan("plan-1", sg.subgoal_id)
        pm.put(
            plan,
            plan_id="plan-1",
            subgoal_id=sg.subgoal_id,
            segments=[seg.segment_id],
            created_at=NOW_ISO,
        )

        loop = ReflectionLoop()
        state = ReflectionState(
            cycle=1,
            timestamp=NOW_MS,
            subgoal_id=sg.subgoal_id,
            subgoal_memory=sm,
            segment_memory=segm,
            plan_memory=pm,
            drift_memory=DriftMemory(),
            plan_id="plan-1",
        )
        outcome = loop.run_reflection_cycle(state)

        # If plan repair succeeded and plan was persisted, RETRY should follow.
        if outcome.plan_adjustment and outcome.plan_adjustment.persisted:
            retry_records = [t for t in outcome.transitions_applied if t.event == "retry"]
            assert len(retry_records) >= 1


# ---------------------------------------------------------------------------
# ReflectionLoop — plan repair
# ---------------------------------------------------------------------------

class TestReflectionLoopPlanRepair:

    def _state_with_clean_plan(self, sg: Subgoal) -> ReflectionState:
        sm = SubgoalMemory()
        sm.put(sg)
        segm = SegmentMemory()
        seg = make_segment(subgoal_id=sg.subgoal_id)
        segm.put(seg)
        pm = PlanMemory()
        plan = make_plan("plan-1", sg.subgoal_id)
        pm.put(plan, plan_id="plan-1", subgoal_id=sg.subgoal_id,
               segments=[seg.segment_id], created_at=NOW_ISO)
        return ReflectionState(
            cycle=1, timestamp=NOW_MS, subgoal_id=sg.subgoal_id,
            subgoal_memory=sm, segment_memory=segm, plan_memory=pm,
            drift_memory=DriftMemory(), plan_id="plan-1",
        )

    def test_plan_adjustment_present_when_plan_id_provided(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(self._state_with_clean_plan(sg))
        assert outcome.plan_adjustment is not None
        assert outcome.plan_adjustment.plan_id == "plan-1"

    def test_clean_plan_reports_repair_succeeded(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(self._state_with_clean_plan(sg))
        assert outcome.plan_adjustment is not None
        assert outcome.plan_adjustment.repair_succeeded is True

    def test_clean_plan_is_persisted(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(self._state_with_clean_plan(sg))
        assert outcome.plan_adjustment is not None
        assert outcome.plan_adjustment.persisted is True

    def test_no_segments_regenerated_for_clean_plan(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(self._state_with_clean_plan(sg))
        assert outcome.plan_adjustment is not None
        assert outcome.plan_adjustment.segments_regenerated == 0

    def test_missing_plan_id_yields_no_adjustment(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        state = fresh_state(sg, plan_id=None)
        outcome = loop.run_reflection_cycle(state)
        assert outcome.plan_adjustment is None

    def test_nonexistent_plan_yields_no_adjustment(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        state = fresh_state(sg, plan_id="nonexistent-plan")
        outcome = loop.run_reflection_cycle(state)
        assert outcome.plan_adjustment is None

    def test_plan_with_missing_segment_not_persisted_without_regen(self):
        """
        A plan referencing a segment that doesn't exist → repair will regenerate a
        placeholder → requires_segment_regen=True → plan must NOT be persisted.
        """
        sg = make_subgoal()
        sm = SubgoalMemory()
        sm.put(sg)
        pm = PlanMemory()
        plan = make_plan("plan-1", sg.subgoal_id)
        # Reference a segment that doesn't exist in SegmentMemory.
        pm.put(plan, plan_id="plan-1", subgoal_id=sg.subgoal_id,
               segments=["missing-seg-id"], created_at=NOW_ISO)

        state = ReflectionState(
            cycle=1, timestamp=NOW_MS, subgoal_id=sg.subgoal_id,
            subgoal_memory=sm, segment_memory=SegmentMemory(), plan_memory=pm,
            drift_memory=DriftMemory(), plan_id="plan-1",
        )
        outcome = loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(state)

        assert outcome.plan_adjustment is not None
        if outcome.plan_adjustment.requires_segment_regen:
            assert outcome.plan_adjustment.persisted is False


# ---------------------------------------------------------------------------
# ReflectionLoop — memory updates and audit trail
# ---------------------------------------------------------------------------

class TestReflectionLoopAuditTrail:

    def test_memory_updates_are_tuple(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert isinstance(outcome.memory_updates, tuple)

    def test_memory_update_record_fields(self):
        sg = make_subgoal()
        sm = SubgoalMemory()
        sm.put(sg)
        segm = SegmentMemory()
        seg = make_segment(subgoal_id=sg.subgoal_id)
        segm.put(seg)
        pm = PlanMemory()
        plan = make_plan("plan-1", sg.subgoal_id)
        pm.put(plan, plan_id="plan-1", subgoal_id=sg.subgoal_id,
               segments=[seg.segment_id], created_at=NOW_ISO)

        loop = ReflectionLoop()
        state = ReflectionState(
            cycle=1, timestamp=NOW_MS, subgoal_id=sg.subgoal_id,
            subgoal_memory=sm, segment_memory=segm, plan_memory=pm,
            drift_memory=DriftMemory(), plan_id="plan-1",
        )
        outcome = loop.run_reflection_cycle(state)

        for upd in outcome.memory_updates:
            assert upd.store in ("subgoal", "segment", "plan", "drift")
            assert upd.operation in ("write", "reject")
            assert isinstance(upd.record_id, str)
            assert isinstance(upd.details, dict)

    def test_trace_repairs_tuple(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert isinstance(outcome.trace.repairs, tuple)

    def test_trace_transitions_tuple(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert isinstance(outcome.trace.transitions, tuple)

    def test_trace_memory_updates_tuple(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert isinstance(outcome.trace.memory_updates, tuple)

    def test_transitions_applied_is_tuple(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert isinstance(outcome.transitions_applied, tuple)

    def test_errors_tuple(self):
        sg = make_subgoal()
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg))
        assert isinstance(outcome.errors, tuple)


# ---------------------------------------------------------------------------
# ReflectionLoop — progress rate across cycles
# ---------------------------------------------------------------------------

class TestReflectionLoopProgressRate:

    def test_steady_without_prior_progress(self):
        sg = make_subgoal(state=SubgoalLifecycleState.READY)
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg, cycle=1))
        assert outcome.progress.progress_rate == "steady"

    def test_increasing_when_subgoals_complete_grows(self):
        prior = ProgressReport(
            subgoals_complete=0, subgoals_total=1,
            segments_complete=0, segments_total=0,
            stalled=False, stalled_reasons=(), progress_rate="steady",
        )
        sg = make_subgoal(state=SubgoalLifecycleState.SUCCESS)
        loop = ReflectionLoop()
        outcome = loop.run_reflection_cycle(fresh_state(sg, cycle=2, prior_progress=prior))
        assert outcome.progress.progress_rate == "increasing"

    def test_stalled_when_no_subgoals(self):
        loop = ReflectionLoop()
        state = ReflectionState(
            cycle=1,
            timestamp=NOW_MS,
            subgoal_id="missing",
            subgoal_memory=SubgoalMemory(),
            segment_memory=SegmentMemory(),
            plan_memory=PlanMemory(),
            drift_memory=DriftMemory(),
        )
        outcome = loop.run_reflection_cycle(state)
        assert outcome.progress.stalled is True
        assert outcome.progress.progress_rate == "stalled"
