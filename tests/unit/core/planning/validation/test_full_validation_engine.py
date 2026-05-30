"""
Tests for Phase 2.5.4 — Full Validation Rules.

Covers:
  - validation_types construction
  - validate_subgoal
  - validate_segment
  - validate_plan
  - validate_memory
  - validate_safety
  - validate_transition_before
  - validate_transition_after
  - validate_pipeline (composable)
  - JSON-serialisability of FullValidationResult
"""
from __future__ import annotations

import dataclasses
import json
from typing import List, Optional, Set, Tuple

import pytest

from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord, SubgoalMemorySnapshot
from src.core.memory.segment_memory_types import SegmentMemoryRecord, SegmentMemorySnapshot
from src.core.memory.plan_memory_types import PlanMemoryRecord, PlanMemorySnapshot
from src.core.memory.drift_memory_types import DriftEvent, DriftMemorySnapshot

from src.core.types.subgoal import SubgoalLifecycleState
from src.core.planning.subgoals.transition_rules import SubgoalEvent
from src.core.planning.drift.drift_types import DriftSignal, DriftSignalClass

from src.core.planning.validation import (
    FullValidationEngine,
    FullValidationResult,
    ValidationIssue,
    SubgoalValidationResult,
    SegmentValidationResult,
    PlanRecordValidationResult,
    MemoryValidationResult,
    SafetyValidationResult,
    TransitionValidationError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _subgoal(
    subgoal_id: str = "sg-1",
    parent_id: Optional[str] = None,
    state: str = "created",
    goal: str = "Do something",
    context: Optional[dict] = None,
    metadata: Optional[dict] = None,
    created_at: int = 1000,
) -> SubgoalMemoryRecord:
    return SubgoalMemoryRecord(
        subgoal_id=subgoal_id,
        parent_id=parent_id,
        state=state,
        goal=goal,
        context=context or {},
        metadata=metadata or {},
        created_at=created_at,
    )


def _segment(
    segment_id: str = "seg-1",
    parent_id: Optional[str] = None,
    subgoal_id: str = "sg-1",
    state: Optional[str] = None,
    content: Optional[List[str]] = None,
    created_at: str = "2024-01-01T00:00:00Z",
    context: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> SegmentMemoryRecord:
    return SegmentMemoryRecord(
        segment_id=segment_id,
        parent_id=parent_id,
        subgoal_id=subgoal_id,
        state=state,
        content=content if content is not None else ["step 1"],
        created_at=created_at,
        context=context or {},
        metadata=metadata or {},
    )


def _plan(
    plan_id: str = "plan-1",
    subgoal_id: str = "sg-1",
    segments: Optional[List[str]] = None,
    created_at: str = "2024-01-01T00:00:00Z",
    metadata: Optional[dict] = None,
    intent: str = "Do something",
    targetskillid: str = "skill-1",
    arguments: Optional[dict] = None,
    reasoning_summary: str = "reasoning",
) -> PlanMemoryRecord:
    return PlanMemoryRecord(
        plan_id=plan_id,
        subgoal_id=subgoal_id,
        segments=segments if segments is not None else ["seg-1"],
        created_at=created_at,
        metadata=metadata or {},
        intent=intent,
        targetskillid=targetskillid,
        arguments=arguments or {},
        reasoning_summary=reasoning_summary,
    )


def _signal(
    type: str = "missing_segment",
    severity: str = "high",
    signal_class: str = "structural",
    timestamp: str = "2024-01-01T00:00:00Z",
    metadata: Optional[dict] = None,
) -> DriftSignal:
    return DriftSignal(
        type=type,
        severity=severity,
        timestamp=timestamp,
        signal_class=signal_class,
        metadata=metadata or {},
    )


# Minimal mock memory stores (snapshot-only)
class _MockSubgoalMemory:
    def __init__(self, records: Tuple[SubgoalMemoryRecord, ...] = ()) -> None:
        self._records = records

    def snapshot(self) -> SubgoalMemorySnapshot:
        return SubgoalMemorySnapshot(records=self._records)


class _MockSegmentMemory:
    def __init__(self, records: Tuple[SegmentMemoryRecord, ...] = ()) -> None:
        self._records = records

    def snapshot(self) -> SegmentMemorySnapshot:
        return SegmentMemorySnapshot(records=self._records)


class _MockPlanMemory:
    def __init__(self, records: Tuple[PlanMemoryRecord, ...] = ()) -> None:
        self._records = records

    def snapshot(self) -> PlanMemorySnapshot:
        return PlanMemorySnapshot(records=self._records)


class _MockDriftMemory:
    def __init__(self, events: Tuple[DriftEvent, ...] = ()) -> None:
        self._events = events

    def snapshot(self) -> DriftMemorySnapshot:
        return DriftMemorySnapshot(events=self._events)


@pytest.fixture
def engine() -> FullValidationEngine:
    return FullValidationEngine()


# ---------------------------------------------------------------------------
# validation_types — construction
# ---------------------------------------------------------------------------

class TestValidationTypes:
    def test_validation_issue_construction(self):
        issue = ValidationIssue(
            code="test_code", message="test", field="field", severity="error"
        )
        assert issue.code == "test_code"
        assert issue.severity == "error"
        assert issue.field == "field"

    def test_validation_issue_warning_severity(self):
        issue = ValidationIssue(code="x", message="y", field=None, severity="warning")
        assert issue.severity == "warning"
        assert issue.field is None

    def test_subgoal_validation_result_construction(self):
        result = SubgoalValidationResult(
            valid=True,
            errors=(),
            warnings=(),
            state="created",
            metadata_ok=True,
            drift_affected=False,
            repair_affected=False,
        )
        assert result.valid is True
        assert result.state == "created"

    def test_full_validation_result_all_none_stages(self):
        result = FullValidationResult(
            valid=True, errors=(), warnings=(),
            subgoal=None, segment=None, plan=None, memory=None, safety=None,
        )
        assert result.subgoal is None
        assert result.valid is True

    def test_transition_validation_error_defaults(self):
        err = TransitionValidationError(
            from_state="created", event="succeed",
            reason="forbidden", stage="pre",
        )
        assert err.allowed is False
        assert err.stage == "pre"


# ---------------------------------------------------------------------------
# validate_subgoal
# ---------------------------------------------------------------------------

class TestValidateSubgoal:
    def test_valid_record(self, engine):
        r = _subgoal()
        result = engine.validate_subgoal(r)
        assert result.valid is True
        assert result.errors == ()
        assert result.state == "created"
        assert result.metadata_ok is True
        assert result.drift_affected is False
        assert result.repair_affected is False

    def test_missing_subgoal_id(self, engine):
        r = _subgoal(subgoal_id="")
        result = engine.validate_subgoal(r)
        assert result.valid is False
        codes = {e.code for e in result.errors}
        assert "subgoal_id_required" in codes

    def test_missing_goal(self, engine):
        r = _subgoal(goal="")
        result = engine.validate_subgoal(r)
        assert result.valid is False
        codes = {e.code for e in result.errors}
        assert "goal_required" in codes

    def test_invalid_state(self, engine):
        r = _subgoal(state="not_a_state")
        result = engine.validate_subgoal(r)
        assert result.valid is False
        codes = {e.code for e in result.errors}
        assert "invalid_state" in codes

    def test_negative_created_at(self, engine):
        r = _subgoal(created_at=-1)
        result = engine.validate_subgoal(r)
        assert result.valid is False

    def test_self_parent(self, engine):
        r = _subgoal(subgoal_id="sg-1", parent_id="sg-1")
        result = engine.validate_subgoal(r)
        assert result.valid is False
        codes = {e.code for e in result.errors}
        assert "self_parent" in codes

    def test_drift_affected_when_signals_provided(self, engine):
        r = _subgoal()
        result = engine.validate_subgoal(r, drift_signals=[_signal()])
        assert result.drift_affected is True

    def test_not_drift_affected_without_signals(self, engine):
        r = _subgoal()
        result = engine.validate_subgoal(r, drift_signals=[])
        assert result.drift_affected is False

    def test_repair_affected_from_metadata(self, engine):
        r = _subgoal(metadata={"repair_in_progress": True})
        result = engine.validate_subgoal(r)
        assert result.repair_affected is True

    def test_not_repair_affected_by_default(self, engine):
        r = _subgoal()
        result = engine.validate_subgoal(r)
        assert result.repair_affected is False

    def test_metadata_ok_false_on_bad_metadata(self, engine):
        # Non-JSON-pure metadata
        r = _subgoal(metadata={"bad": object()})
        result = engine.validate_subgoal(r)
        assert result.valid is False
        assert result.metadata_ok is False

    def test_all_error_issues_have_error_severity(self, engine):
        r = _subgoal(subgoal_id="", goal="")
        result = engine.validate_subgoal(r)
        assert all(e.severity == "error" for e in result.errors)

    def test_all_valid_states(self, engine):
        for state in SubgoalLifecycleState:
            r = _subgoal(state=state.value)
            result = engine.validate_subgoal(r)
            # Only state should affect validity here
            assert "invalid_state" not in {e.code for e in result.errors}


# ---------------------------------------------------------------------------
# validate_segment
# ---------------------------------------------------------------------------

class TestValidateSegment:
    def test_valid_record(self, engine):
        r = _segment()
        result = engine.validate_segment(r)
        assert result.valid is True
        assert result.segment_id == "seg-1"
        assert result.steps_ok is True
        assert result.timestamp_ok is True
        assert result.chain_ok is None     # no known_segment_ids provided
        assert result.subgoal_ok is None   # no known_subgoal_ids provided

    def test_missing_segment_id(self, engine):
        r = _segment(segment_id="")
        result = engine.validate_segment(r)
        assert result.valid is False
        codes = {e.code for e in result.errors}
        assert "segment_id_required" in codes

    def test_missing_subgoal_id(self, engine):
        r = _segment(subgoal_id="")
        result = engine.validate_segment(r)
        assert result.valid is False

    def test_empty_content(self, engine):
        r = _segment(content=[])
        result = engine.validate_segment(r)
        assert result.valid is False
        assert result.steps_ok is False

    def test_non_string_content(self, engine):
        r = _segment(content=[1, 2])  # type: ignore[list-item]
        result = engine.validate_segment(r)
        assert result.valid is False
        assert result.steps_ok is False

    def test_bad_timestamp(self, engine):
        r = _segment(created_at="not-a-date")
        result = engine.validate_segment(r)
        assert result.valid is False
        assert result.timestamp_ok is False

    def test_self_parent(self, engine):
        r = _segment(segment_id="seg-1", parent_id="seg-1")
        result = engine.validate_segment(r)
        assert result.valid is False

    def test_subgoal_ok_true_when_known(self, engine):
        r = _segment(subgoal_id="sg-1")
        result = engine.validate_segment(r, known_subgoal_ids={"sg-1"})
        assert result.subgoal_ok is True

    def test_subgoal_ok_false_when_unknown(self, engine):
        r = _segment(subgoal_id="sg-X")
        result = engine.validate_segment(r, known_subgoal_ids={"sg-1"})
        assert result.subgoal_ok is False
        assert result.valid is False

    def test_chain_ok_true_when_parent_known(self, engine):
        r = _segment(segment_id="seg-2", parent_id="seg-1")
        result = engine.validate_segment(r, known_segment_ids={"seg-1"})
        assert result.chain_ok is True

    def test_chain_ok_false_when_parent_missing(self, engine):
        r = _segment(segment_id="seg-2", parent_id="seg-X")
        result = engine.validate_segment(r, known_segment_ids={"seg-1"})
        assert result.chain_ok is False
        assert result.valid is False
        codes = {e.code for e in result.errors}
        assert "broken_parent_chain" in codes

    def test_chain_ok_true_when_no_parent(self, engine):
        r = _segment(parent_id=None)
        result = engine.validate_segment(r, known_segment_ids={"seg-1"})
        assert result.chain_ok is True

    def test_drift_affected(self, engine):
        r = _segment()
        result = engine.validate_segment(r, drift_signals=[_signal()])
        assert result.drift_affected is True

    def test_repair_affected_from_metadata(self, engine):
        r = _segment(metadata={"repair_in_progress": True})
        result = engine.validate_segment(r)
        assert result.repair_affected is True

    def test_all_context_provided_valid(self, engine):
        r = _segment(segment_id="seg-1", subgoal_id="sg-1")
        result = engine.validate_segment(
            r,
            known_subgoal_ids={"sg-1"},
            known_segment_ids={"seg-1"},
        )
        assert result.valid is True
        assert result.subgoal_ok is True
        assert result.chain_ok is True


# ---------------------------------------------------------------------------
# validate_plan
# ---------------------------------------------------------------------------

class TestValidatePlan:
    def test_valid_record(self, engine):
        r = _plan()
        result = engine.validate_plan(r)
        assert result.valid is True
        assert result.plan_id == "plan-1"
        assert result.metadata_ok is True
        assert result.structural_ok is True
        assert result.consistency_ok is None  # no context
        assert result.drift_affected is False

    def test_missing_plan_id(self, engine):
        r = _plan(plan_id="")
        result = engine.validate_plan(r)
        assert result.valid is False
        codes = {e.code for e in result.errors}
        assert "plan_id_required" in codes

    def test_missing_subgoal_id(self, engine):
        r = _plan(subgoal_id="")
        result = engine.validate_plan(r)
        assert result.valid is False

    def test_missing_intent(self, engine):
        r = _plan(intent="")
        result = engine.validate_plan(r)
        assert result.valid is False

    def test_bad_timestamp(self, engine):
        r = _plan(created_at="not-a-date")
        result = engine.validate_plan(r)
        assert result.valid is False

    def test_empty_segments_list_is_structural_ok(self, engine):
        # segments=[] must NOT be rejected (repair uses empty segment lists)
        r = _plan(segments=[])
        result = engine.validate_plan(r)
        assert result.structural_ok is True

    def test_consistency_ok_true_when_references_resolved(self, engine):
        r = _plan(subgoal_id="sg-1", segments=["seg-1"])
        result = engine.validate_plan(
            r,
            known_subgoal_ids={"sg-1"},
            known_segment_ids={"seg-1"},
        )
        assert result.consistency_ok is True
        assert result.valid is True

    def test_consistency_ok_false_unknown_subgoal(self, engine):
        r = _plan(subgoal_id="sg-X", segments=["seg-1"])
        result = engine.validate_plan(
            r,
            known_subgoal_ids={"sg-1"},
            known_segment_ids={"seg-1"},
        )
        assert result.consistency_ok is False
        assert result.valid is False

    def test_consistency_ok_false_unknown_segment(self, engine):
        r = _plan(subgoal_id="sg-1", segments=["seg-X"])
        result = engine.validate_plan(
            r,
            known_subgoal_ids={"sg-1"},
            known_segment_ids={"seg-1"},
        )
        assert result.consistency_ok is False
        assert result.valid is False

    def test_consistency_none_without_context(self, engine):
        r = _plan()
        result = engine.validate_plan(r)
        assert result.consistency_ok is None

    def test_drift_affected_with_signals(self, engine):
        r = _plan()
        result = engine.validate_plan(r, drift_signals=[_signal()])
        assert result.drift_affected is True

    def test_metadata_ok_false_on_bad_metadata(self, engine):
        r = _plan(metadata={"bad": object()})
        result = engine.validate_plan(r)
        assert result.valid is False
        assert result.metadata_ok is False


# ---------------------------------------------------------------------------
# validate_memory
# ---------------------------------------------------------------------------

class TestValidateMemory:
    def _empty_stores(self):
        return (
            _MockSubgoalMemory(),
            _MockSegmentMemory(),
            _MockPlanMemory(),
            _MockDriftMemory(),
        )

    def test_empty_stores_valid(self, engine):
        sg, se, pl, dr = self._empty_stores()
        result = engine.validate_memory(sg, se, pl, dr)
        assert result.valid is True
        assert result.subgoal_count == 0
        assert result.segment_count == 0
        assert result.plan_count == 0
        assert result.drift_count == 0
        assert result.referential_ok is True
        assert result.chain_ok is True

    def test_valid_stores_with_records(self, engine):
        sg_rec = _subgoal(subgoal_id="sg-1")
        se_rec = _segment(segment_id="seg-1", subgoal_id="sg-1")
        pl_rec = _plan(plan_id="pl-1", subgoal_id="sg-1", segments=["seg-1"])

        sg = _MockSubgoalMemory((sg_rec,))
        se = _MockSegmentMemory((se_rec,))
        pl = _MockPlanMemory((pl_rec,))
        dr = _MockDriftMemory()

        result = engine.validate_memory(sg, se, pl, dr)
        assert result.valid is True
        assert result.subgoal_count == 1
        assert result.segment_count == 1
        assert result.plan_count == 1
        assert result.referential_ok is True
        assert result.chain_ok is True

    def test_segment_unknown_subgoal_fails_referential(self, engine):
        sg_rec = _subgoal(subgoal_id="sg-1")
        se_rec = _segment(segment_id="seg-1", subgoal_id="sg-X")  # unknown subgoal

        sg = _MockSubgoalMemory((sg_rec,))
        se = _MockSegmentMemory((se_rec,))
        pl = _MockPlanMemory()
        dr = _MockDriftMemory()

        result = engine.validate_memory(sg, se, pl, dr)
        assert result.valid is False
        assert result.referential_ok is False
        codes = {e.code for e in result.errors}
        assert "unknown_subgoal_reference" in codes

    def test_broken_parent_chain_detected(self, engine):
        sg_rec = _subgoal(subgoal_id="sg-1")
        se_rec = _segment(
            segment_id="seg-2", subgoal_id="sg-1", parent_id="seg-X"  # missing parent
        )

        sg = _MockSubgoalMemory((sg_rec,))
        se = _MockSegmentMemory((se_rec,))
        pl = _MockPlanMemory()
        dr = _MockDriftMemory()

        result = engine.validate_memory(sg, se, pl, dr)
        assert result.valid is False
        assert result.chain_ok is False
        codes = {e.code for e in result.errors}
        assert "broken_parent_chain" in codes

    def test_plan_unknown_segment_fails_referential(self, engine):
        sg_rec = _subgoal(subgoal_id="sg-1")
        se_rec = _segment(segment_id="seg-1", subgoal_id="sg-1")
        pl_rec = _plan(plan_id="pl-1", subgoal_id="sg-1", segments=["seg-X"])

        sg = _MockSubgoalMemory((sg_rec,))
        se = _MockSegmentMemory((se_rec,))
        pl = _MockPlanMemory((pl_rec,))
        dr = _MockDriftMemory()

        result = engine.validate_memory(sg, se, pl, dr)
        assert result.valid is False
        assert result.referential_ok is False

    def test_invalid_subgoal_record_detected(self, engine):
        sg_rec = _subgoal(subgoal_id="", goal="")  # governance violations
        sg = _MockSubgoalMemory((sg_rec,))
        se = _MockSegmentMemory()
        pl = _MockPlanMemory()
        dr = _MockDriftMemory()

        result = engine.validate_memory(sg, se, pl, dr)
        assert result.valid is False

    def test_counts_reflect_store_sizes(self, engine):
        sg1 = _subgoal(subgoal_id="sg-1")
        sg2 = _subgoal(subgoal_id="sg-2")
        se1 = _segment(segment_id="seg-1", subgoal_id="sg-1")

        sg = _MockSubgoalMemory((sg1, sg2))
        se = _MockSegmentMemory((se1,))
        pl = _MockPlanMemory()
        dr = _MockDriftMemory()

        result = engine.validate_memory(sg, se, pl, dr)
        assert result.subgoal_count == 2
        assert result.segment_count == 1
        assert result.plan_count == 0
        assert result.drift_count == 0


# ---------------------------------------------------------------------------
# validate_safety
# ---------------------------------------------------------------------------

class TestValidateSafety:
    def test_valid_record_no_drift(self, engine):
        r = _subgoal(state="created")
        result = engine.validate_safety(r)
        assert result.valid is True
        assert result.forbidden_state is False
        assert result.forbidden_transition is False
        assert result.drift_blocked is False
        assert result.governance_blocked is False
        assert result.repair_blocked is False

    def test_forbidden_state_invalid_value(self, engine):
        r = _subgoal(state="not_a_state")
        result = engine.validate_safety(r)
        assert result.forbidden_state is True
        assert result.valid is False
        codes = {e.code for e in result.errors}
        assert "forbidden_state" in codes

    def test_forbidden_transition_for_terminal_state(self, engine):
        r = _subgoal(state="closed")
        result = engine.validate_safety(r)
        assert result.forbidden_transition is True
        # closed is lifecycle-terminal — a warning, not an error
        codes = {w.code for w in result.warnings}
        assert "lifecycle_terminal_state" in codes

    def test_drift_blocked_severe_in_running(self, engine):
        # 5 high-severity signals → SEVERE or CRITICAL classification
        signals = [_signal("missing_segment", "high", "structural")] * 5
        r = _subgoal(state="running")
        result = engine.validate_safety(r, drift_signals=signals)
        assert result.drift_blocked is True
        assert result.valid is False
        codes = {e.code for e in result.errors}
        assert "drift_blocked" in codes

    def test_drift_blocked_critical_in_active(self, engine):
        # Many high signals → CRITICAL
        signals = [_signal("broken_parent_chain", "high", "structural")] * 8
        r = _subgoal(state="active")
        result = engine.validate_safety(r, drift_signals=signals)
        assert result.drift_blocked is True
        assert result.valid is False

    def test_drift_not_blocked_in_non_active_state(self, engine):
        # Even severe drift doesn't block a state that's not running/active
        signals = [_signal("missing_segment", "high", "structural")] * 5
        r = _subgoal(state="created")
        result = engine.validate_safety(r, drift_signals=signals)
        assert result.drift_blocked is False

    def test_moderate_drift_produces_warning(self, engine):
        # 3 medium signals → MODERATE classification
        signals = [_signal("stale_timestamp", "medium", "temporal")] * 3
        r = _subgoal(state="running")
        result = engine.validate_safety(r, drift_signals=signals)
        # Moderate drift = warning, not blocking error
        assert result.drift_blocked is False
        codes = {w.code for w in result.warnings}
        assert "moderate_drift_in_active_state" in codes

    def test_governance_blocked_on_invalid_record(self, engine):
        r = _subgoal(subgoal_id="")  # governance violation
        result = engine.validate_safety(r)
        assert result.governance_blocked is True
        assert result.valid is False

    def test_repair_blocked_in_running(self, engine):
        r = _subgoal(state="running", metadata={"repair_in_progress": True})
        result = engine.validate_safety(r)
        assert result.repair_blocked is True
        codes = {w.code for w in result.warnings}
        assert "repair_blocked" in codes

    def test_repair_blocked_in_active(self, engine):
        r = _subgoal(state="active", metadata={"repair_in_progress": True})
        result = engine.validate_safety(r)
        assert result.repair_blocked is True

    def test_repair_not_blocked_in_non_active_state(self, engine):
        r = _subgoal(state="created", metadata={"repair_in_progress": True})
        result = engine.validate_safety(r)
        assert result.repair_blocked is False

    def test_no_signals_no_blocking(self, engine):
        r = _subgoal(state="running")
        result = engine.validate_safety(r, drift_signals=[])
        assert result.drift_blocked is False
        assert result.valid is True

    def test_minor_drift_does_not_block(self, engine):
        # 1 low signal → MINOR drift
        signals = [_signal("stale_timestamp", "low", "temporal")]
        r = _subgoal(state="running")
        result = engine.validate_safety(r, drift_signals=signals)
        assert result.drift_blocked is False
        assert result.valid is True

    def test_valid_for_all_non_running_states_no_drift(self, engine):
        non_active = [
            "created", "validated", "ready", "success", "failed",
            "blocked", "retrying", "pending", "satisfied", "abandoned",
        ]
        for state in non_active:
            r = _subgoal(state=state)
            result = engine.validate_safety(r)
            assert result.drift_blocked is False
            assert result.governance_blocked is False
            assert result.repair_blocked is False


# ---------------------------------------------------------------------------
# validate_transition_before
# ---------------------------------------------------------------------------

class TestValidateTransitionBefore:
    def test_allowed_transition_no_error(self, engine):
        result = engine.validate_transition_before(
            SubgoalLifecycleState.CREATED, SubgoalEvent.VALIDATE
        )
        assert result is None

    def test_allowed_transition_running_no_drift(self, engine):
        result = engine.validate_transition_before(
            SubgoalLifecycleState.READY, SubgoalEvent.START
        )
        assert result is None

    def test_forbidden_event_from_state(self, engine):
        # CREATED cannot receive SUCCEED
        result = engine.validate_transition_before(
            SubgoalLifecycleState.CREATED, SubgoalEvent.SUCCEED
        )
        assert result is not None
        assert result.stage == "pre"
        assert result.allowed is False

    def test_event_from_terminal_state(self, engine):
        # SUCCESS is event-terminal
        result = engine.validate_transition_before(
            SubgoalLifecycleState.SUCCESS, SubgoalEvent.VALIDATE
        )
        assert result is not None
        assert result.stage == "pre"

    def test_drift_blocks_transition_to_running(self, engine):
        # READY + START → RUNNING, but severe drift blocks it
        signals = [_signal("missing_segment", "high", "structural")] * 5
        result = engine.validate_transition_before(
            SubgoalLifecycleState.READY, SubgoalEvent.START, signals
        )
        assert result is not None
        assert result.stage == "pre"
        assert "running" in result.reason

    def test_drift_blocks_transition_to_active(self, engine):
        # PENDING + ACTIVATE → ACTIVE, blocked by severe drift
        signals = [_signal("broken_parent_chain", "high", "structural")] * 5
        result = engine.validate_transition_before(
            SubgoalLifecycleState.PENDING, SubgoalEvent.ACTIVATE, signals
        )
        assert result is not None
        assert "active" in result.reason

    def test_drift_does_not_block_transition_to_ready(self, engine):
        # VALIDATED + ACTIVATE → READY, not RUNNING/ACTIVE — not blocked
        signals = [_signal("missing_segment", "high", "structural")] * 5
        result = engine.validate_transition_before(
            SubgoalLifecycleState.VALIDATED, SubgoalEvent.ACTIVATE, signals
        )
        assert result is None

    def test_minor_drift_does_not_block_running(self, engine):
        # MINOR drift does not block
        signals = [_signal("stale_timestamp", "low", "temporal")]
        result = engine.validate_transition_before(
            SubgoalLifecycleState.READY, SubgoalEvent.START, signals
        )
        assert result is None

    def test_retrying_resume_blocked_by_severe_drift(self, engine):
        signals = [_signal("repair_loop", "high", "behavioural")] * 5
        result = engine.validate_transition_before(
            SubgoalLifecycleState.RETRYING, SubgoalEvent.RESUME, signals
        )
        assert result is not None
        assert "running" in result.reason

    def test_no_signals_all_valid_transitions_pass(self, engine):
        valid_pairs = [
            (SubgoalLifecycleState.CREATED, SubgoalEvent.VALIDATE),
            (SubgoalLifecycleState.VALIDATED, SubgoalEvent.ACTIVATE),
            (SubgoalLifecycleState.READY, SubgoalEvent.START),
            (SubgoalLifecycleState.RUNNING, SubgoalEvent.SUCCEED),
            (SubgoalLifecycleState.RUNNING, SubgoalEvent.FAIL),
            (SubgoalLifecycleState.RUNNING, SubgoalEvent.BLOCK),
            (SubgoalLifecycleState.BLOCKED, SubgoalEvent.UNBLOCK),
            (SubgoalLifecycleState.BLOCKED, SubgoalEvent.FAIL),
            (SubgoalLifecycleState.FAILED, SubgoalEvent.RETRY),
            (SubgoalLifecycleState.RETRYING, SubgoalEvent.RESUME),
            (SubgoalLifecycleState.PENDING, SubgoalEvent.ACTIVATE),
            (SubgoalLifecycleState.ACTIVE, SubgoalEvent.SUCCEED),
            (SubgoalLifecycleState.ACTIVE, SubgoalEvent.FAIL),
        ]
        for state, event in valid_pairs:
            result = engine.validate_transition_before(state, event)
            assert result is None, f"Expected None for ({state.value}, {event.value})"


# ---------------------------------------------------------------------------
# validate_transition_after
# ---------------------------------------------------------------------------

class TestValidateTransitionAfter:
    def test_valid_event_driven_transition(self, engine):
        # CREATED → VALIDATED (via validate event)
        result = engine.validate_transition_after("created", "validated")
        assert result is None

    def test_valid_direct_transition(self, engine):
        # SATISFIED → CLOSED (direct only)
        result = engine.validate_transition_after("satisfied", "closed")
        assert result is None

    def test_valid_failed_to_closed(self, engine):
        result = engine.validate_transition_after("failed", "closed")
        assert result is None

    def test_valid_abandoned_to_closed(self, engine):
        result = engine.validate_transition_after("abandoned", "closed")
        assert result is None

    def test_same_state_always_valid(self, engine):
        for state in SubgoalLifecycleState:
            result = engine.validate_transition_after(state.value, state.value)
            assert result is None, f"Same-state write should be valid: {state.value}"

    def test_invalid_skip_transition(self, engine):
        # CREATED → RUNNING skips intermediate states
        result = engine.validate_transition_after("created", "running")
        assert result is not None
        assert result.stage == "post"
        assert result.allowed is False

    def test_invalid_regression(self, engine):
        # RUNNING → CREATED is a regression
        result = engine.validate_transition_after("running", "created")
        assert result is not None

    def test_invalid_from_terminal(self, engine):
        # CLOSED → anything is forbidden
        result = engine.validate_transition_after("closed", "created")
        assert result is not None
        assert result.stage == "post"

    def test_all_valid_event_transitions_pass(self, engine):
        from src.core.planning.transitions.subgoal_table import SUBGOAL_EVENT_TRANSITIONS
        for (old, _event), new in SUBGOAL_EVENT_TRANSITIONS.items():
            result = engine.validate_transition_after(old, new)
            assert result is None, (
                f"Event transition {old!r} → {new!r} should pass post-validation"
            )

    def test_all_valid_direct_transitions_pass(self, engine):
        from src.core.planning.transitions.subgoal_table import SUBGOAL_DIRECT_TRANSITIONS
        for old_state, reachable in SUBGOAL_DIRECT_TRANSITIONS.items():
            for new_state in reachable:
                result = engine.validate_transition_after(old_state, new_state)
                assert result is None, (
                    f"Direct transition {old_state!r} → {new_state!r} "
                    "should pass post-validation"
                )

    def test_returns_post_stage_on_failure(self, engine):
        result = engine.validate_transition_after("success", "running")
        assert result is not None
        assert result.stage == "post"
        assert result.from_state == "success"


# ---------------------------------------------------------------------------
# validate_pipeline
# ---------------------------------------------------------------------------

class TestValidatePipeline:
    def test_empty_pipeline_is_valid(self, engine):
        result = engine.validate_pipeline()
        assert result.valid is True
        assert result.subgoal is None
        assert result.segment is None
        assert result.plan is None
        assert result.memory is None
        assert result.safety is None
        assert result.errors == ()
        assert result.warnings == ()

    def test_subgoal_only_valid(self, engine):
        r = _subgoal()
        result = engine.validate_pipeline(subgoal_record=r)
        assert result.valid is True
        assert result.subgoal is not None
        assert result.segment is None
        assert result.safety is not None  # safety always runs with subgoal

    def test_subgoal_only_invalid(self, engine):
        r = _subgoal(subgoal_id="")
        result = engine.validate_pipeline(subgoal_record=r)
        assert result.valid is False
        assert len(result.errors) > 0

    def test_segment_without_subgoal_runs_independently(self, engine):
        r = _segment()
        result = engine.validate_pipeline(segment_record=r)
        assert result.valid is True
        assert result.subgoal is None
        assert result.segment is not None

    def test_plan_without_memory_has_none_consistency(self, engine):
        r = _plan()
        result = engine.validate_pipeline(plan_record=r)
        assert result.plan is not None
        assert result.plan.consistency_ok is None

    def test_memory_stage_skipped_when_any_store_absent(self, engine):
        # Provide only subgoal_memory — memory stage requires all four
        result = engine.validate_pipeline(
            subgoal_memory=_MockSubgoalMemory()
        )
        assert result.memory is None

    def test_memory_stage_runs_when_all_stores_provided(self, engine):
        result = engine.validate_pipeline(
            subgoal_memory=_MockSubgoalMemory(),
            segment_memory=_MockSegmentMemory(),
            plan_memory=_MockPlanMemory(),
            drift_memory=_MockDriftMemory(),
        )
        assert result.memory is not None
        assert result.memory.valid is True

    def test_full_pipeline_valid(self, engine):
        sg = _subgoal(subgoal_id="sg-1")
        se = _segment(segment_id="seg-1", subgoal_id="sg-1")
        pl = _plan(plan_id="pl-1", subgoal_id="sg-1", segments=["seg-1"])

        result = engine.validate_pipeline(
            subgoal_record=sg,
            segment_record=se,
            plan_record=pl,
            subgoal_memory=_MockSubgoalMemory((sg,)),
            segment_memory=_MockSegmentMemory((se,)),
            plan_memory=_MockPlanMemory((pl,)),
            drift_memory=_MockDriftMemory(),
        )
        assert result.valid is True
        assert result.subgoal is not None
        assert result.segment is not None
        assert result.plan is not None
        assert result.memory is not None
        assert result.safety is not None

    def test_pipeline_aggregates_errors_from_all_stages(self, engine):
        bad_sg = _subgoal(subgoal_id="")
        bad_se = _segment(subgoal_id="")
        result = engine.validate_pipeline(
            subgoal_record=bad_sg,
            segment_record=bad_se,
        )
        assert result.valid is False
        assert len(result.errors) > 1  # errors from multiple stages

    def test_drift_signals_propagate_through_pipeline(self, engine):
        sg = _subgoal(state="running")
        signals = [_signal("missing_segment", "high", "structural")] * 5
        result = engine.validate_pipeline(
            subgoal_record=sg,
            drift_signals=signals,
        )
        assert result.subgoal is not None
        assert result.subgoal.drift_affected is True
        # Safety should be blocked
        assert result.safety is not None
        assert result.safety.drift_blocked is True

    def test_safety_stage_not_run_without_subgoal(self, engine):
        result = engine.validate_pipeline(
            segment_record=_segment(),
        )
        assert result.safety is None

    def test_pipeline_none_drift_signals_treated_as_empty(self, engine):
        sg = _subgoal()
        result = engine.validate_pipeline(subgoal_record=sg, drift_signals=None)
        assert result.subgoal is not None
        assert result.subgoal.drift_affected is False


# ---------------------------------------------------------------------------
# JSON-serialisability
# ---------------------------------------------------------------------------

class TestJsonSerialisability:
    def test_empty_pipeline_result_is_json_serialisable(self, engine):
        result = engine.validate_pipeline()
        d = dataclasses.asdict(result)
        json.dumps(d)  # must not raise

    def test_full_pipeline_result_is_json_serialisable(self, engine):
        sg = _subgoal(subgoal_id="sg-1")
        se = _segment(segment_id="seg-1", subgoal_id="sg-1")
        pl = _plan(plan_id="pl-1", subgoal_id="sg-1", segments=["seg-1"])

        result = engine.validate_pipeline(
            subgoal_record=sg,
            segment_record=se,
            plan_record=pl,
            subgoal_memory=_MockSubgoalMemory((sg,)),
            segment_memory=_MockSegmentMemory((se,)),
            plan_memory=_MockPlanMemory((pl,)),
            drift_memory=_MockDriftMemory(),
            drift_signals=[_signal()],
        )
        d = dataclasses.asdict(result)
        json.dumps(d)  # must not raise

    def test_validation_issue_is_json_serialisable(self, engine):
        issue = ValidationIssue(
            code="test", message="test message", field="field", severity="error"
        )
        d = dataclasses.asdict(issue)
        json.dumps(d)

    def test_transition_validation_error_is_json_serialisable(self, engine):
        err = engine.validate_transition_before(
            SubgoalLifecycleState.CREATED, SubgoalEvent.SUCCEED
        )
        assert err is not None
        d = dataclasses.asdict(err)
        json.dumps(d)

    def test_safety_result_is_json_serialisable(self, engine):
        r = _subgoal(state="running")
        signals = [_signal("missing_segment", "high", "structural")] * 5
        safety = engine.validate_safety(r, drift_signals=signals)
        d = dataclasses.asdict(safety)
        json.dumps(d)
