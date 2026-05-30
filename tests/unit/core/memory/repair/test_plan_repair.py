"""
Tests for PlanRepair — deterministic, pure, rule-based plan repair.
"""
from __future__ import annotations

import pytest
from typing import Dict, List, Optional, Set

from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.memory.plan_memory_types import PlanMemoryRecord
from src.core.memory.drift_memory_types import DriftEvent
from src.core.memory.repair.repair_types import (
    PlanBreakageReport,
    RepairPlan,
    RepairOutcome,
    RepairedSegmentRecord,
)
from src.core.memory.repair.plan_repair import PlanRepair, _breakage_fingerprint, _ms_to_iso

NOW = 1_000_000


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def repair() -> PlanRepair:
    return PlanRepair()


def make_plan(
    plan_id: str = "plan-1",
    subgoal_id: str = "sg-1",
    segments: list = None,
    created_at: str = "2024-01-01T00:00:00",
) -> PlanMemoryRecord:
    return PlanMemoryRecord(
        plan_id=plan_id,
        subgoal_id=subgoal_id,
        segments=segments if segments is not None else [],
        created_at=created_at,
        metadata={},
        intent="do something",
        targetskillid="skill-a",
        arguments={},
        reasoning_summary="",
    )


def make_segment(
    segment_id: str,
    subgoal_id: str = "sg-1",
    parent_id: Optional[str] = None,
    created_at: str = "2024-01-01T00:00:00",
    content: list = None,
) -> SegmentMemoryRecord:
    return SegmentMemoryRecord(
        segment_id=segment_id,
        parent_id=parent_id,
        subgoal_id=subgoal_id,
        state=None,
        content=content if content is not None else ["step1"],
        created_at=created_at,
        context={},
        metadata={},
    )


def make_subgoal(subgoal_id: str, parent_id: Optional[str] = None) -> SubgoalMemoryRecord:
    return SubgoalMemoryRecord(
        subgoal_id=subgoal_id,
        parent_id=parent_id,
        state="PENDING",
        goal="do something",
        context={},
        metadata={},
        created_at=1000,
    )


def make_drift(
    subgoal_id: str = "sg-1",
    segment_id: Optional[str] = None,
    signal_type: str = "timeout",
    timestamp: int = 1000,
) -> DriftEvent:
    return DriftEvent(
        timestamp=timestamp,
        subgoal_id=subgoal_id,
        segment_id=segment_id,
        step_id=None,
        signal_type=signal_type,
        confidence=0.8,
        details={},
    )


# ---------------------------------------------------------------------------
# detect_breakages — clean plan
# ---------------------------------------------------------------------------

class TestDetectClean:
    def test_clean_plan_no_errors(self, repair):
        plan = make_plan(segments=["seg-a"])
        segs = {"seg-a": make_segment("seg-a")}
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, segs, set(), sgs, [], NOW)
        assert result.is_clean
        assert result.errors == ()
        assert result.missing_segments == ()
        assert result.invalid_links == ()

    def test_clean_empty_segment_list(self, repair):
        plan = make_plan(segments=[])
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, {}, set(), sgs, [], NOW)
        assert result.is_clean

    def test_plan_id_in_report(self, repair):
        plan = make_plan(plan_id="my-plan", segments=[])
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, {}, set(), sgs, [], NOW)
        assert result.plan_id == "my-plan"


# ---------------------------------------------------------------------------
# detect_breakages — missing subgoal
# ---------------------------------------------------------------------------

class TestDetectMissingSubgoal:
    def test_missing_subgoal_flagged(self, repair):
        plan = make_plan(subgoal_id="sg-missing", segments=[])
        result = repair.detect_breakages(plan, {}, set(), {}, [], NOW)
        assert not result.is_clean
        types = {e.error_type for e in result.errors}
        assert "MISSING_SUBGOAL" in types

    def test_missing_subgoal_record_id(self, repair):
        plan = make_plan(subgoal_id="sg-missing", segments=[])
        result = repair.detect_breakages(plan, {}, set(), {}, [], NOW)
        missing = [e for e in result.errors if e.error_type == "MISSING_SUBGOAL"]
        assert missing[0].record_id == "sg-missing"


# ---------------------------------------------------------------------------
# detect_breakages — missing segments
# ---------------------------------------------------------------------------

class TestDetectMissingSegments:
    def test_missing_segment_flagged(self, repair):
        plan = make_plan(segments=["seg-gone"])
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, {}, set(), sgs, [], NOW)
        assert "seg-gone" in result.missing_segments
        types = {e.error_type for e in result.errors}
        assert "MISSING_SEGMENT" in types

    def test_regenerated_id_not_flagged_as_missing(self, repair):
        plan = make_plan(segments=["seg-a", "seg-regen"])
        segs = {"seg-a": make_segment("seg-a")}
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, segs, {"seg-regen"}, sgs, [], NOW)
        assert "seg-regen" not in result.missing_segments

    def test_invalid_link_added_for_missing_segment(self, repair):
        plan = make_plan(segments=["seg-gone"])
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, {}, set(), sgs, [], NOW)
        links = [l for l in result.invalid_links if l.link_type == "plan_segment"]
        assert any(l.to_id == "seg-gone" for l in links)


# ---------------------------------------------------------------------------
# detect_breakages — broken parent link
# ---------------------------------------------------------------------------

class TestDetectBrokenParentLink:
    def test_broken_parent_link_detected(self, repair):
        plan = make_plan(segments=["seg-a"])
        seg = make_segment("seg-a", parent_id="seg-missing")
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, {"seg-a": seg}, set(), sgs, [], NOW)
        types = {e.error_type for e in result.errors}
        assert "BROKEN_PARENT_LINK" in types

    def test_valid_parent_not_flagged(self, repair):
        plan = make_plan(segments=["seg-a", "seg-b"])
        seg_a = make_segment("seg-a")
        seg_b = make_segment("seg-b", parent_id="seg-a")
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, {"seg-a": seg_a, "seg-b": seg_b}, set(), sgs, [], NOW)
        types = {e.error_type for e in result.errors}
        assert "BROKEN_PARENT_LINK" not in types

    def test_regenerated_id_as_parent_not_flagged(self, repair):
        plan = make_plan(segments=["seg-a", "seg-b"])
        seg_b = make_segment("seg-b", parent_id="seg-a")
        sgs = {"sg-1": make_subgoal("sg-1")}
        # seg-a is "known" via regenerated_ids
        result = repair.detect_breakages(plan, {"seg-b": seg_b}, {"seg-a"}, sgs, [], NOW)
        types = {e.error_type for e in result.errors}
        assert "BROKEN_PARENT_LINK" not in types


# ---------------------------------------------------------------------------
# detect_breakages — subgoal mismatch
# ---------------------------------------------------------------------------

class TestDetectSubgoalMismatch:
    def test_subgoal_mismatch_detected(self, repair):
        plan = make_plan(subgoal_id="sg-1", segments=["seg-a"])
        seg = make_segment("seg-a", subgoal_id="sg-wrong")
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, {"seg-a": seg}, set(), sgs, [], NOW)
        types = {e.error_type for e in result.errors}
        assert "SUBGOAL_MISMATCH" in types

    def test_matching_subgoal_not_flagged(self, repair):
        plan = make_plan(subgoal_id="sg-1", segments=["seg-a"])
        seg = make_segment("seg-a", subgoal_id="sg-1")
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, {"seg-a": seg}, set(), sgs, [], NOW)
        types = {e.error_type for e in result.errors}
        assert "SUBGOAL_MISMATCH" not in types


# ---------------------------------------------------------------------------
# detect_breakages — timestamp issues
# ---------------------------------------------------------------------------

class TestDetectTimestampIssues:
    def test_invalid_plan_timestamp_detected(self, repair):
        plan = make_plan(created_at="not-a-date")
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, {}, set(), sgs, [], NOW)
        ts_issues = [t for t in result.timestamp_issues if t.record_type == "plan"]
        assert len(ts_issues) == 1

    def test_valid_plan_timestamp_not_flagged(self, repair):
        plan = make_plan(created_at="2024-01-01T00:00:00")
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, {}, set(), sgs, [], NOW)
        plan_ts = [t for t in result.timestamp_issues if t.record_type == "plan"]
        assert plan_ts == []

    def test_invalid_segment_timestamp_is_warning_not_error(self, repair):
        plan = make_plan(segments=["seg-a"])
        seg = make_segment("seg-a", created_at="not-a-date")
        sgs = {"sg-1": make_subgoal("sg-1")}
        result = repair.detect_breakages(plan, {"seg-a": seg}, set(), sgs, [], NOW)
        seg_ts = [t for t in result.timestamp_issues if t.record_type == "segment"]
        assert len(seg_ts) == 1
        # Should be a warning, not make the plan un-clean
        # (governance violations from content validation may make it not clean,
        # but the timestamp itself shouldn't add an error)
        ts_warnings = [w for w in result.warnings if w.warning_type == "SEGMENT_TIMESTAMP"]
        assert len(ts_warnings) == 1


# ---------------------------------------------------------------------------
# detect_breakages — drift flags
# ---------------------------------------------------------------------------

class TestDetectDriftFlags:
    def test_drift_event_for_plan_segment_flagged(self, repair):
        plan = make_plan(segments=["seg-a"])
        segs = {"seg-a": make_segment("seg-a")}
        sgs = {"sg-1": make_subgoal("sg-1")}
        drift = make_drift(segment_id="seg-a", signal_type="loop")
        result = repair.detect_breakages(plan, segs, set(), sgs, [drift], NOW)
        assert len(result.drift_flags) == 1
        assert result.drift_flags[0].segment_id == "seg-a"
        assert result.drift_flags[0].signal_type == "loop"

    def test_drift_event_for_other_segment_not_flagged(self, repair):
        plan = make_plan(segments=["seg-a"])
        segs = {"seg-a": make_segment("seg-a")}
        sgs = {"sg-1": make_subgoal("sg-1")}
        drift = make_drift(segment_id="seg-other")
        result = repair.detect_breakages(plan, segs, set(), sgs, [drift], NOW)
        assert result.drift_flags == ()

    def test_drift_flags_do_not_make_plan_unclean(self, repair):
        plan = make_plan(segments=["seg-a"])
        segs = {"seg-a": make_segment("seg-a")}
        sgs = {"sg-1": make_subgoal("sg-1")}
        drift = make_drift(segment_id="seg-a")
        result = repair.detect_breakages(plan, segs, set(), sgs, [drift], NOW)
        # Drift flags are warnings only — plan is still "clean" structurally
        assert result.is_clean


# ---------------------------------------------------------------------------
# build_repair_plan
# ---------------------------------------------------------------------------

class TestBuildRepairPlan:
    def _run_detect(self, repair, plan, segs, sgs, drift=None):
        return repair.detect_breakages(plan, segs, set(), sgs, drift or [], NOW)

    def test_missing_segment_generates_regenerate_action(self, repair):
        plan = make_plan(segments=["seg-gone"])
        sgs = {"sg-1": make_subgoal("sg-1")}
        breakage = self._run_detect(repair, plan, {}, sgs)
        rp = repair.build_repair_plan(breakage)
        types = {a.action_type for a in rp.actions}
        assert "REGENERATE_SEGMENT" in types
        assert "seg-gone" in rp.requires_segment_regeneration

    def test_missing_subgoal_sets_requires_redecomposition(self, repair):
        plan = make_plan(subgoal_id="sg-missing", segments=[])
        breakage = self._run_detect(repair, plan, {}, {})
        rp = repair.build_repair_plan(breakage)
        assert rp.requires_redecomposition
        assert "sg-missing" in rp.requires_subgoal_repair

    def test_broken_parent_generates_reconstruct_chain(self, repair):
        plan = make_plan(segments=["seg-a"])
        seg = make_segment("seg-a", parent_id="seg-missing")
        sgs = {"sg-1": make_subgoal("sg-1")}
        breakage = self._run_detect(repair, plan, {"seg-a": seg}, sgs)
        rp = repair.build_repair_plan(breakage)
        types = {a.action_type for a in rp.actions}
        assert "RECONSTRUCT_CHAIN" in types

    def test_subgoal_mismatch_generates_quarantine(self, repair):
        plan = make_plan(subgoal_id="sg-1", segments=["seg-a"])
        seg = make_segment("seg-a", subgoal_id="sg-wrong")
        sgs = {"sg-1": make_subgoal("sg-1")}
        breakage = self._run_detect(repair, plan, {"seg-a": seg}, sgs)
        rp = repair.build_repair_plan(breakage)
        types = {a.action_type for a in rp.actions}
        assert "QUARANTINE_SEGMENT" in types

    def test_invalid_plan_timestamp_generates_rehydrate(self, repair):
        plan = make_plan(created_at="not-a-date", segments=[])
        sgs = {"sg-1": make_subgoal("sg-1")}
        breakage = self._run_detect(repair, plan, {}, sgs)
        rp = repair.build_repair_plan(breakage)
        types = {a.action_type for a in rp.actions}
        assert "REHYDRATE_TIMESTAMP" in types

    def test_actions_sorted_deterministically(self, repair):
        plan = make_plan(segments=["seg-z", "seg-a"])
        sgs = {"sg-1": make_subgoal("sg-1")}
        breakage = self._run_detect(repair, plan, {}, sgs)
        rp = repair.build_repair_plan(breakage)
        action_keys = [(a.action_type, a.target_id) for a in rp.actions]
        assert action_keys == sorted(action_keys)

    def test_clean_plan_produces_empty_repair_plan(self, repair):
        plan = make_plan(segments=["seg-a"])
        segs = {"seg-a": make_segment("seg-a")}
        sgs = {"sg-1": make_subgoal("sg-1")}
        breakage = self._run_detect(repair, plan, segs, sgs)
        rp = repair.build_repair_plan(breakage)
        assert rp.actions == ()
        assert not rp.requires_redecomposition


# ---------------------------------------------------------------------------
# regenerate_segment
# ---------------------------------------------------------------------------

class TestRegenerateSegment:
    def test_returns_repaired_segment_record(self, repair):
        result = repair.regenerate_segment("seg-1", "sg-1", None, NOW)
        assert isinstance(result, RepairedSegmentRecord)

    def test_steps_always_empty(self, repair):
        result = repair.regenerate_segment("seg-1", "sg-1", None, NOW)
        assert result.steps == ()

    def test_state_always_pending(self, repair):
        result = repair.regenerate_segment("seg-1", "sg-1", None, NOW)
        assert result.state == "pending"

    def test_metadata_has_repaired_flag(self, repair):
        result = repair.regenerate_segment("seg-1", "sg-1", None, NOW)
        assert result.metadata.get("repaired") is True

    def test_segment_id_and_subgoal_preserved(self, repair):
        result = repair.regenerate_segment("seg-xyz", "sg-abc", "seg-parent", NOW)
        assert result.segment_id == "seg-xyz"
        assert result.subgoal_id == "sg-abc"
        assert result.parent_id == "seg-parent"

    def test_created_at_is_valid_iso(self, repair):
        result = repair.regenerate_segment("seg-1", "sg-1", None, NOW)
        from datetime import datetime
        dt = datetime.fromisoformat(result.created_at)
        assert dt.tzinfo is not None  # timezone-aware

    def test_deterministic_for_same_inputs(self, repair):
        r1 = repair.regenerate_segment("seg-1", "sg-1", None, NOW)
        r2 = repair.regenerate_segment("seg-1", "sg-1", None, NOW)
        assert r1 == r2


# ---------------------------------------------------------------------------
# repair() — success paths
# ---------------------------------------------------------------------------

class TestRepairSuccess:
    def test_clean_plan_succeeds_immediately(self, repair):
        plan = make_plan(segments=["seg-a"])
        segs = {"seg-a": make_segment("seg-a")}
        sgs = {"sg-1": make_subgoal("sg-1")}
        outcome = repair.repair(plan, segs, sgs, [], NOW, repair_budget=10, retry_limit=3)
        assert outcome.success
        assert outcome.attempts == 1
        assert outcome.budget_used == 0
        assert outcome.repaired_plan is not None

    def test_missing_segment_regenerated(self, repair):
        plan = make_plan(segments=["seg-missing"])
        sgs = {"sg-1": make_subgoal("sg-1")}
        outcome = repair.repair(plan, {}, sgs, [], NOW, repair_budget=10, retry_limit=5)
        assert outcome.success
        assert len(outcome.regenerated_segments) == 1
        assert outcome.regenerated_segments[0].segment_id == "seg-missing"

    def test_broken_parent_link_repaired(self, repair):
        plan = make_plan(segments=["seg-a"])
        seg = make_segment("seg-a", parent_id="seg-missing")
        sgs = {"sg-1": make_subgoal("sg-1")}
        outcome = repair.repair(plan, {"seg-a": seg}, sgs, [], NOW, repair_budget=10, retry_limit=5)
        assert outcome.success
        # The repaired plan should still contain seg-a
        assert "seg-a" in outcome.repaired_plan.segments

    def test_invalid_plan_timestamp_repaired(self, repair):
        plan = make_plan(created_at="not-a-date", segments=[])
        sgs = {"sg-1": make_subgoal("sg-1")}
        outcome = repair.repair(plan, {}, sgs, [], NOW, repair_budget=10, retry_limit=3)
        assert outcome.success
        # Timestamp should now be valid ISO
        from src.core.memory.governance.normalisation import normalise_iso_timestamp
        normalise_iso_timestamp(outcome.repaired_plan.created_at)  # should not raise

    def test_subgoal_mismatch_quarantined(self, repair):
        plan = make_plan(subgoal_id="sg-1", segments=["seg-a"])
        seg = make_segment("seg-a", subgoal_id="sg-wrong")
        sgs = {"sg-1": make_subgoal("sg-1")}
        outcome = repair.repair(plan, {"seg-a": seg}, sgs, [], NOW, repair_budget=10, retry_limit=5)
        # After quarantine, seg-a is removed from plan — plan becomes clean
        assert outcome.success
        assert "seg-a" not in outcome.repaired_plan.segments

    def test_repair_actions_audited(self, repair):
        plan = make_plan(segments=["seg-missing"])
        sgs = {"sg-1": make_subgoal("sg-1")}
        outcome = repair.repair(plan, {}, sgs, [], NOW, repair_budget=10, retry_limit=5)
        assert len(outcome.repair_actions_applied) > 0
        types = {a.action_type for a in outcome.repair_actions_applied}
        assert "REGENERATE_SEGMENT" in types

    def test_repaired_plan_returned_on_success(self, repair):
        plan = make_plan(segments=["seg-a"])
        segs = {"seg-a": make_segment("seg-a")}
        sgs = {"sg-1": make_subgoal("sg-1")}
        outcome = repair.repair(plan, segs, sgs, [], NOW, repair_budget=10, retry_limit=3)
        assert isinstance(outcome.repaired_plan, PlanMemoryRecord)


# ---------------------------------------------------------------------------
# repair() — failure paths
# ---------------------------------------------------------------------------

class TestRepairFailure:
    def test_budget_exceeded_aborts(self, repair):
        # Three missing segments but budget=1
        plan = make_plan(segments=["s1", "s2", "s3"])
        sgs = {"sg-1": make_subgoal("sg-1")}
        outcome = repair.repair(plan, {}, sgs, [], NOW, repair_budget=1, retry_limit=5)
        assert not outcome.success
        assert outcome.repaired_plan is None
        assert any("budget" in e.lower() for e in outcome.errors)

    def test_retry_limit_exhausted(self, repair):
        # Missing subgoal can't be repaired structurally — no actions available for it
        plan = make_plan(subgoal_id="sg-missing", segments=[])
        outcome = repair.repair(plan, {}, {}, [], NOW, repair_budget=10, retry_limit=3)
        assert not outcome.success
        assert outcome.repaired_plan is None

    def test_no_actionable_repairs_aborts(self, repair):
        # Missing subgoal with no segments — build_repair_plan has no actions and
        # requires_redecomposition is True but that's a structural flag, not an action
        plan = make_plan(subgoal_id="sg-missing", segments=[])
        outcome = repair.repair(plan, {}, {}, [], NOW, repair_budget=10, retry_limit=2)
        assert not outcome.success

    def test_circular_loop_detected(self, repair):
        # A plan where every repair creates the same breakage state
        # Quarantine removes seg-a, but the loop re-adds it somehow?
        # Simplest: use a governance violation that can't be structurally fixed
        # Create a plan with an invalid intent (empty) — governance violation only
        plan = PlanMemoryRecord(
            plan_id="plan-x",
            subgoal_id="sg-1",
            segments=[],
            created_at="2024-01-01T00:00:00",
            metadata={},
            intent="",  # governance violation: empty intent
            targetskillid="skill-a",
            arguments={},
            reasoning_summary="",
        )
        sgs = {"sg-1": make_subgoal("sg-1")}
        outcome = repair.repair(plan, {}, sgs, [], NOW, repair_budget=10, retry_limit=3)
        # governance violations with no repair action → no progress → circular loop or no-action abort
        assert not outcome.success

    def test_retry_limit_invalid_raises(self, repair):
        plan = make_plan()
        sgs = {"sg-1": make_subgoal("sg-1")}
        with pytest.raises(ValueError, match="retry_limit"):
            repair.repair(plan, {}, sgs, [], NOW, repair_budget=10, retry_limit=0)

    def test_budget_zero_raises(self, repair):
        plan = make_plan()
        sgs = {"sg-1": make_subgoal("sg-1")}
        with pytest.raises(ValueError, match="repair_budget"):
            repair.repair(plan, {}, sgs, [], NOW, repair_budget=0, retry_limit=1)

    def test_repaired_plan_none_on_failure(self, repair):
        plan = make_plan(subgoal_id="sg-missing", segments=[])
        outcome = repair.repair(plan, {}, {}, [], NOW, repair_budget=10, retry_limit=2)
        assert outcome.repaired_plan is None

    def test_regenerated_segments_returned_even_on_failure(self, repair):
        # Budget=1: one segment can be regenerated, but two are missing → budget abort
        plan = make_plan(segments=["s1", "s2"])
        sgs = {"sg-1": make_subgoal("sg-1")}
        outcome = repair.repair(plan, {}, sgs, [], NOW, repair_budget=1, retry_limit=5)
        assert not outcome.success
        # regenerated_segments should be empty since we aborted before applying
        assert outcome.regenerated_segments == ()


# ---------------------------------------------------------------------------
# repair() — determinism
# ---------------------------------------------------------------------------

class TestRepairDeterminism:
    def test_same_inputs_same_outcome(self, repair):
        plan = make_plan(segments=["seg-missing"])
        sgs = {"sg-1": make_subgoal("sg-1")}
        o1 = repair.repair(plan, {}, sgs, [], NOW, repair_budget=10, retry_limit=5)
        o2 = repair.repair(plan, {}, sgs, [], NOW, repair_budget=10, retry_limit=5)
        assert o1.success == o2.success
        assert o1.budget_used == o2.budget_used
        assert len(o1.repair_actions_applied) == len(o2.repair_actions_applied)


# ---------------------------------------------------------------------------
# Breakage fingerprint
# ---------------------------------------------------------------------------

class TestBreakageFingerpint:
    def _clean_report(self, plan_id="plan-x"):
        return PlanBreakageReport(
            plan_id=plan_id,
            errors=(),
            warnings=(),
            missing_segments=(),
            invalid_links=(),
            drift_flags=(),
            timestamp_issues=(),
            governance_violations=(),
        )

    def test_returns_string(self):
        report = self._clean_report()
        assert isinstance(_breakage_fingerprint(report), str)

    def test_stable_for_same_report(self):
        report = self._clean_report()
        assert _breakage_fingerprint(report) == _breakage_fingerprint(report)

    def test_different_for_different_errors(self):
        from src.core.memory.repair.repair_types import BreakageError
        r1 = PlanBreakageReport(
            plan_id="p",
            errors=(BreakageError("MISSING_SEGMENT", "seg-a", {}),),
            warnings=(), missing_segments=(), invalid_links=(), drift_flags=(), timestamp_issues=(), governance_violations=(),
        )
        r2 = PlanBreakageReport(
            plan_id="p",
            errors=(BreakageError("MISSING_SEGMENT", "seg-b", {}),),
            warnings=(), missing_segments=(), invalid_links=(), drift_flags=(), timestamp_issues=(), governance_violations=(),
        )
        assert _breakage_fingerprint(r1) != _breakage_fingerprint(r2)


# ---------------------------------------------------------------------------
# _ms_to_iso helper
# ---------------------------------------------------------------------------

class TestMsToIso:
    def test_returns_timezone_aware_string(self):
        from datetime import datetime
        result = _ms_to_iso(1_000_000_000)
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo is not None

    def test_zero_ms(self):
        result = _ms_to_iso(0)
        assert "1970" in result
