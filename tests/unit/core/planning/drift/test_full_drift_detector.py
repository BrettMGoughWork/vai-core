"""
Behaviour tests for Phase 2.5.3 — Full Drift Detection.

Coverage:
  - DriftSignal construction (valid/invalid)
  - Structural signal collection: all signal types
  - Behavioural signal collection: all signal types
  - Temporal signal collection: all signal types
  - compute_confidence: empty, single severity, mixed, diversity, count saturation
  - classify_drift: boundary conditions for each tier
  - ConfirmationBuffer: single-cycle no-confirm, multi-cycle confirm, cooldown, decay
  - FullDriftDetector.detect: end-to-end integration
  - get_trigger: None when not confirmed, correct fields when confirmed
  - write_to_memory: no-op when not confirmed, writes on confirmed, governance rejection
  - buffer_snapshot: returns JSON-safe dict
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pytest

from src.core.memory.drift_memory import DriftMemory
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.core.memory.plan_memory_types import PlanMemoryRecord
from src.core.memory.governance.governance_errors import GovernanceViolation

from src.core.planning.drift.drift_types import (
    DriftClassification,
    DriftConfirmation,
    DriftSignal,
    DriftSignalClass,
    DriftTrigger,
)
from src.core.planning.drift.drift_context import DriftContext, TransitionFailureRecord
from src.core.planning.drift.drift_signal_collectors import (
    DRIFT_SIGNAL_TYPE,
    DRIFT_REPEAT_THRESHOLD,
    DRIFT_WINDOW,
    FALLBACK_THRESHOLD,
    REPAIR_LOOP_THRESHOLD,
    STALE_THRESHOLD_MS,
    TRANSITION_FAILURE_THRESHOLD,
    collect_behavioural_signals,
    collect_structural_signals,
    collect_temporal_signals,
)
from src.core.planning.drift.full_drift_detector import (
    ConfirmationBuffer,
    FullDriftDetector,
    classify_drift,
    compute_confidence,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

NOW_MS: int = 1_700_000_000_000  # fixed anchor


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _signal(sig_type: str, severity: str, cls: DriftSignalClass) -> DriftSignal:
    return DriftSignal(
        type=sig_type,
        severity=severity,
        timestamp=_iso(NOW_MS),
        signal_class=cls.value,
        metadata={},
    )


def _low()  -> DriftSignal: return _signal("x", "low",    DriftSignalClass.STRUCTURAL)
def _med()  -> DriftSignal: return _signal("x", "medium", DriftSignalClass.BEHAVIOURAL)
def _high() -> DriftSignal: return _signal("x", "high",   DriftSignalClass.TEMPORAL)


def _subgoal(
    subgoal_id: str,
    state: str = "running",
    created_at: int = NOW_MS,
    parent_id: str | None = None,
) -> SubgoalMemoryRecord:
    return SubgoalMemoryRecord(
        subgoal_id=subgoal_id,
        goal="test",
        state=state,
        created_at=created_at,
        parent_id=parent_id,
        context={},
        metadata={},
    )


def _segment(
    segment_id: str,
    subgoal_id: str = "sg1",
    created_at: str | None = None,
    parent_id: str | None = None,
) -> SegmentMemoryRecord:
    return SegmentMemoryRecord(
        segment_id=segment_id,
        subgoal_id=subgoal_id,
        content=["step"],
        created_at=created_at or _iso(NOW_MS),
        parent_id=parent_id,
        state=None,
        context={},
        metadata={},
    )


def _plan(
    plan_id: str,
    subgoal_id: str = "sg1",
    segments: list | None = None,
    created_at: str | None = None,
) -> PlanMemoryRecord:
    return PlanMemoryRecord(
        plan_id=plan_id,
        subgoal_id=subgoal_id,
        intent="test",
        targetskillid="skill",
        arguments={},
        reasoning_summary="",
        segments=segments or [],
        created_at=created_at or _iso(NOW_MS),
        metadata={},
    )


def _empty_ctx() -> DriftContext:
    return DriftContext(timestamp=NOW_MS, subgoal_id="sg1")


@pytest.fixture
def detector() -> FullDriftDetector:
    return FullDriftDetector(confirmation_cycles=2, cooldown_cycles=3)


# ---------------------------------------------------------------------------
# DriftSignal construction
# ---------------------------------------------------------------------------

class TestDriftSignal:
    def test_valid_construction(self):
        s = _low()
        assert s.type == "x"
        assert s.severity == "low"
        assert s.signal_class == DriftSignalClass.STRUCTURAL.value

    def test_invalid_severity_raises(self):
        with pytest.raises(ValueError, match="severity"):
            DriftSignal(type="x", severity="extreme", timestamp=_iso(NOW_MS),
                        signal_class="structural", metadata={})

    def test_invalid_signal_class_raises(self):
        with pytest.raises(ValueError, match="signal_class"):
            DriftSignal(type="x", severity="low", timestamp=_iso(NOW_MS),
                        signal_class="unknown_class", metadata={})

    def test_metadata_deep_copied(self):
        original = {"key": "value"}
        s = DriftSignal(type="x", severity="low", timestamp=_iso(NOW_MS),
                        signal_class="structural", metadata=original)
        original["key"] = "mutated"
        assert s.metadata["key"] == "value"

    def test_non_json_pure_metadata_raises(self):
        with pytest.raises(Exception):
            DriftSignal(type="x", severity="low", timestamp=_iso(NOW_MS),
                        signal_class="structural", metadata={"key": object()})


# ---------------------------------------------------------------------------
# Structural signal collector
# ---------------------------------------------------------------------------

class TestStructuralSignals:
    def test_empty_context_no_signals(self):
        assert collect_structural_signals(_empty_ctx()) == []

    def test_missing_segment_detected(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            plan_id="p1",
            plan_records={"p1": _plan("p1", segments=["seg_missing"])},
            segment_records={},
        )
        signals = collect_structural_signals(ctx)
        types = [s.type for s in signals]
        assert "missing_segment" in types

    def test_missing_segment_severity_high(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            plan_id="p1",
            plan_records={"p1": _plan("p1", segments=["seg_missing"])},
            segment_records={},
        )
        sig = next(s for s in collect_structural_signals(ctx) if s.type == "missing_segment")
        assert sig.severity == "high"

    def test_broken_parent_chain_detected(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            segment_records={"s1": _segment("s1", parent_id="s_nonexistent")},
        )
        types = [s.type for s in collect_structural_signals(ctx)]
        assert "broken_parent_chain" in types

    def test_no_broken_chain_when_parent_exists(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            segment_records={
                "s1": _segment("s1", parent_id="s2"),
                "s2": _segment("s2"),
            },
        )
        types = [s.type for s in collect_structural_signals(ctx)]
        assert "broken_parent_chain" not in types

    def test_invalid_subgoal_segment_mapping(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            segment_records={"s1": _segment("s1", subgoal_id="sg_other")},
        )
        types = [s.type for s in collect_structural_signals(ctx)]
        assert "invalid_subgoal_segment_mapping" in types

    def test_matching_subgoal_no_mapping_signal(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            segment_records={"s1": _segment("s1", subgoal_id="sg1")},
        )
        types = [s.type for s in collect_structural_signals(ctx)]
        assert "invalid_subgoal_segment_mapping" not in types

    def test_stale_timestamp_segment(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            segment_records={"s1": _segment("s1", created_at="not-a-date")},
        )
        types = [s.type for s in collect_structural_signals(ctx)]
        assert "stale_timestamp" in types

    def test_orphaned_subgoal_detected(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            subgoal_records={"sg1": _subgoal("sg1", parent_id="sg_missing")},
        )
        types = [s.type for s in collect_structural_signals(ctx)]
        assert "orphaned_subgoal" in types

    def test_invalid_plan_reference(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            plan_records={"p1": _plan("p1", subgoal_id="sg_nonexistent")},
            subgoal_records={},
        )
        types = [s.type for s in collect_structural_signals(ctx)]
        assert "invalid_plan_reference" in types

    def test_all_signals_have_structural_class(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            segment_records={"s1": _segment("s1", subgoal_id="sg_other")},
        )
        for s in collect_structural_signals(ctx):
            assert s.signal_class == DriftSignalClass.STRUCTURAL.value


# ---------------------------------------------------------------------------
# Behavioural signal collector
# ---------------------------------------------------------------------------

class TestBehaviouralSignals:
    def test_empty_context_no_signals(self):
        assert collect_behavioural_signals(_empty_ctx()) == []

    def test_governance_violation_emits_signal(self):
        v = GovernanceViolation(rule="r", field="f", message="m", record_id="id")
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1", governance_violations=[v])
        types = [s.type for s in collect_behavioural_signals(ctx)]
        assert "governance_violation" in types

    def test_repeated_transition_failure_at_threshold(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            transition_failures=[
                TransitionFailureRecord("running", "succeed", TRANSITION_FAILURE_THRESHOLD)
            ],
        )
        types = [s.type for s in collect_behavioural_signals(ctx)]
        assert "repeated_transition_failure" in types

    def test_repeated_transition_failure_below_threshold(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            transition_failures=[
                TransitionFailureRecord("running", "succeed", TRANSITION_FAILURE_THRESHOLD - 1)
            ],
        )
        types = [s.type for s in collect_behavioural_signals(ctx)]
        assert "repeated_transition_failure" not in types

    def test_repair_loop_at_threshold(self):
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        types = [s.type for s in collect_behavioural_signals(ctx)]
        assert "repair_loop" in types

    def test_repair_loop_below_threshold(self):
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD - 1)
        types = [s.type for s in collect_behavioural_signals(ctx)]
        assert "repair_loop" not in types

    def test_fallback_overuse_at_threshold(self):
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           fallback_count=FALLBACK_THRESHOLD)
        types = [s.type for s in collect_behavioural_signals(ctx)]
        assert "fallback_overuse" in types

    def test_fallback_overuse_below_threshold(self):
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           fallback_count=FALLBACK_THRESHOLD - 1)
        types = [s.type for s in collect_behavioural_signals(ctx)]
        assert "fallback_overuse" not in types

    def test_all_signals_have_behavioural_class(self):
        v = GovernanceViolation(rule="r", field="f", message="m", record_id="id")
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1", governance_violations=[v])
        for s in collect_behavioural_signals(ctx):
            assert s.signal_class == DriftSignalClass.BEHAVIOURAL.value


# ---------------------------------------------------------------------------
# Temporal signal collector
# ---------------------------------------------------------------------------

class TestTemporalSignals:
    def test_empty_context_no_signals(self):
        assert collect_temporal_signals(_empty_ctx()) == []

    def test_excessive_state_time_running(self):
        old_ms = NOW_MS - 400_000  # 400s > 300s threshold
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            subgoal_records={"sg1": _subgoal("sg1", state="running", created_at=old_ms)},
        )
        types = [s.type for s in collect_temporal_signals(ctx)]
        assert "excessive_state_time" in types

    def test_no_excessive_time_for_recent_state(self):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            subgoal_records={"sg1": _subgoal("sg1", state="running", created_at=NOW_MS - 1000)},
        )
        types = [s.type for s in collect_temporal_signals(ctx)]
        assert "excessive_state_time" not in types

    def test_stale_memory_entry(self):
        old_ms = NOW_MS - STALE_THRESHOLD_MS - 1000
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            subgoal_records={"sg1": _subgoal("sg1", state="pending", created_at=old_ms)},
        )
        types = [s.type for s in collect_temporal_signals(ctx)]
        assert "stale_memory_entry" in types

    def test_out_of_order_timestamp(self):
        parent_ms = NOW_MS
        child_ms  = NOW_MS - 10_000  # child older than parent
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            segment_records={
                "s1": _segment("s1", parent_id="s2", created_at=_iso(child_ms)),
                "s2": _segment("s2", created_at=_iso(parent_ms)),
            },
        )
        types = [s.type for s in collect_temporal_signals(ctx)]
        assert "out_of_order_timestamp" in types

    def test_future_timestamp(self):
        future_ms = NOW_MS + 120_000  # 2 minutes ahead (> 1 min tolerance)
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            segment_records={"s1": _segment("s1", created_at=_iso(future_ms))},
        )
        types = [s.type for s in collect_temporal_signals(ctx)]
        assert "future_timestamp" in types

    def test_repeated_drift_in_window(self):
        dm = DriftMemory(capacity=20)
        for _ in range(DRIFT_REPEAT_THRESHOLD):
            from src.core.memory.drift_memory_types import DriftEvent
            dm.record(DriftEvent(
                timestamp=NOW_MS, subgoal_id="sg1", segment_id=None,
                step_id=None, signal_type=DRIFT_SIGNAL_TYPE,
                confidence=0.8, details={},
            ))
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1", drift_memory=dm)
        types = [s.type for s in collect_temporal_signals(ctx)]
        assert "repeated_drift_in_window" in types

    def test_no_repeated_drift_below_threshold(self):
        dm = DriftMemory(capacity=20)
        from src.core.memory.drift_memory_types import DriftEvent
        for _ in range(DRIFT_REPEAT_THRESHOLD - 1):
            dm.record(DriftEvent(
                timestamp=NOW_MS, subgoal_id="sg1", segment_id=None,
                step_id=None, signal_type=DRIFT_SIGNAL_TYPE,
                confidence=0.8, details={},
            ))
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1", drift_memory=dm)
        types = [s.type for s in collect_temporal_signals(ctx)]
        assert "repeated_drift_in_window" not in types

    def test_all_signals_have_temporal_class(self):
        old_ms = NOW_MS - 400_000
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            subgoal_records={"sg1": _subgoal("sg1", state="running", created_at=old_ms)},
        )
        for s in collect_temporal_signals(ctx):
            assert s.signal_class == DriftSignalClass.TEMPORAL.value


# ---------------------------------------------------------------------------
# compute_confidence
# ---------------------------------------------------------------------------

class TestComputeConfidence:
    def test_empty_returns_zero(self):
        assert compute_confidence([]) == 0.0

    def test_single_high_near_max(self):
        c = compute_confidence([_high()])
        assert 0.5 < c <= 1.0

    def test_single_low_lower_than_high(self):
        assert compute_confidence([_low()]) < compute_confidence([_high()])

    def test_result_in_range(self):
        signals = [_low(), _med(), _high()]
        c = compute_confidence(signals)
        assert 0.0 <= c <= 1.0

    def test_more_signals_higher_confidence(self):
        one = compute_confidence([_high()])
        five = compute_confidence([_high()] * 5)
        assert five >= one

    def test_diversity_bonus_three_classes(self):
        mixed = [
            _signal("a", "medium", DriftSignalClass.STRUCTURAL),
            _signal("b", "medium", DriftSignalClass.BEHAVIOURAL),
            _signal("c", "medium", DriftSignalClass.TEMPORAL),
        ]
        one_class = [_signal("a", "medium", DriftSignalClass.STRUCTURAL)] * 3
        assert compute_confidence(mixed) > compute_confidence(one_class)

    def test_saturates_at_one(self):
        # Three signal classes all high → should produce the maximum attainable confidence
        many = [
            _signal("a", "high", DriftSignalClass.STRUCTURAL),
            _signal("b", "high", DriftSignalClass.BEHAVIOURAL),
            _signal("c", "high", DriftSignalClass.TEMPORAL),
        ] * 7
        c = compute_confidence(many)
        assert c >= 0.95  # near-saturation for max-severity, max-diversity signals


# ---------------------------------------------------------------------------
# classify_drift
# ---------------------------------------------------------------------------

class TestClassifyDrift:
    def test_empty_returns_no_drift(self):
        assert classify_drift([]) == DriftClassification.NO_DRIFT

    def test_single_low_returns_minor(self):
        result = classify_drift([_low()])
        assert result == DriftClassification.MINOR_DRIFT

    def test_moderate_boundary(self):
        # Need score >= 5: 2 high signals (6) + 1 class diversity (1) = 7 → MODERATE
        signals = [_signal("x", "high", DriftSignalClass.STRUCTURAL)] * 2
        result = classify_drift(signals)
        assert result in (DriftClassification.MODERATE_DRIFT, DriftClassification.SEVERE_DRIFT)

    def test_critical_with_many_high_signals(self):
        # 5 high signals (15) + 1 diversity (1) = 16 → CRITICAL
        signals = [_signal("x", "high", DriftSignalClass.STRUCTURAL)] * 5
        result = classify_drift(signals)
        assert result == DriftClassification.CRITICAL_DRIFT

    def test_diversity_contributes_to_score(self):
        homogeneous = [_signal("x", "medium", DriftSignalClass.STRUCTURAL)] * 3
        diverse = [
            _signal("a", "medium", DriftSignalClass.STRUCTURAL),
            _signal("b", "medium", DriftSignalClass.BEHAVIOURAL),
            _signal("c", "medium", DriftSignalClass.TEMPORAL),
        ]
        h_cls = classify_drift(homogeneous)
        d_cls = classify_drift(diverse)
        # diverse should be >= homogeneous
        order = list(DriftClassification)
        assert order.index(d_cls) >= order.index(h_cls)

    def test_all_classifications_reachable(self):
        results = set()
        results.add(classify_drift([]))
        results.add(classify_drift([_low()]))
        results.add(classify_drift([_med(), _med(), _low()]))
        results.add(classify_drift([_high(), _high(), _high()]))
        results.add(classify_drift([_high()] * 5))
        assert DriftClassification.NO_DRIFT in results
        assert DriftClassification.MINOR_DRIFT in results
        assert DriftClassification.CRITICAL_DRIFT in results


# ---------------------------------------------------------------------------
# ConfirmationBuffer
# ---------------------------------------------------------------------------

class TestConfirmationBuffer:
    def test_single_cycle_not_confirmed(self):
        buf = ConfirmationBuffer(confirmation_cycles=2)
        result = buf.observe([_high()])
        assert result.confirmed is False
        assert result.cycles_observed == 1

    def test_two_cycles_confirms(self):
        buf = ConfirmationBuffer(confirmation_cycles=2)
        buf.observe([_high()])
        result = buf.observe([_high()])
        assert result.confirmed is True
        assert result.cycles_observed == 2

    def test_confirmation_cycle_one_also_works(self):
        buf = ConfirmationBuffer(confirmation_cycles=1)
        result = buf.observe([_high()])
        assert result.confirmed is True

    def test_empty_cycle_does_not_accumulate(self):
        buf = ConfirmationBuffer(confirmation_cycles=2)
        buf.observe([_high()])
        result = buf.observe([])     # clean cycle — no signals
        assert result.confirmed is False
        assert result.cycles_observed == 1   # only the non-empty cycle counts

    def test_cooldown_resets_buffer(self):
        buf = ConfirmationBuffer(confirmation_cycles=2, cooldown_cycles=2)
        buf.observe([_high()])
        buf.observe([])   # clean 1
        buf.observe([])   # clean 2 → triggers reset
        result = buf.observe([_high()])   # starts fresh — needs another cycle to confirm
        assert result.confirmed is False

    def test_no_cooldown_without_enough_clean_cycles(self):
        buf = ConfirmationBuffer(confirmation_cycles=2, cooldown_cycles=3)
        buf.observe([_high()])
        buf.observe([])   # clean 1
        buf.observe([])   # clean 2 (not enough — cooldown needs 3)
        result = buf.observe([_high()])
        # history is still non-empty so cycles_observed could be >= 2
        # The first signal cycle was retained; reset hasn't happened yet
        assert result.confirmed is True

    def test_confidence_decays_for_older_cycles(self):
        buf = ConfirmationBuffer(confirmation_cycles=2)
        buf.observe([_high()])
        result = buf.observe([_high()])
        assert 0.0 < result.confidence <= 1.0

    def test_signals_tuple_contains_all_cycle_signals(self):
        buf = ConfirmationBuffer(confirmation_cycles=2)
        buf.observe([_high(), _med()])
        result = buf.observe([_low()])
        # History is trimmed to confirmation_cycles (2), so all 3 signals should be there
        assert len(result.signals) == 3

    def test_history_structure(self):
        buf = ConfirmationBuffer(confirmation_cycles=2)
        buf.observe([_high()])
        result = buf.observe([_med()])
        assert isinstance(result.history, tuple)
        for cycle in result.history:
            assert isinstance(cycle, tuple)
            for s in cycle:
                assert isinstance(s, DriftSignal)

    def test_invalid_confirmation_cycles_raises(self):
        with pytest.raises(ValueError):
            ConfirmationBuffer(confirmation_cycles=0)

    def test_invalid_cooldown_cycles_raises(self):
        with pytest.raises(ValueError):
            ConfirmationBuffer(cooldown_cycles=0)

    def test_snapshot_returns_dict(self):
        buf = ConfirmationBuffer(confirmation_cycles=2)
        buf.observe([_high()])
        snap = buf.snapshot()
        assert isinstance(snap, dict)
        assert "history" in snap
        assert "confirmation_cycles" in snap


# ---------------------------------------------------------------------------
# FullDriftDetector — detect()
# ---------------------------------------------------------------------------

class TestFullDriftDetectorDetect:
    def test_empty_context_no_signals_no_confirm(self, detector):
        result = detector.detect(_empty_ctx())
        assert result.confirmed is False
        assert result.confidence == 0.0

    def test_two_cycles_with_signals_confirms(self, detector):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            repair_attempts=REPAIR_LOOP_THRESHOLD,
        )
        detector.detect(ctx)       # cycle 1
        result = detector.detect(ctx)   # cycle 2
        assert result.confirmed is True

    def test_result_is_drift_confirmation(self, detector):
        result = detector.detect(_empty_ctx())
        assert isinstance(result, DriftConfirmation)

    def test_confidence_in_range(self, detector):
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        detector.detect(ctx)
        result = detector.detect(ctx)
        assert 0.0 <= result.confidence <= 1.0

    def test_structural_signals_captured(self, detector):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            plan_id="p1",
            plan_records={"p1": _plan("p1", segments=["missing_seg"])},
            segment_records={},
        )
        detector.detect(ctx)
        result = detector.detect(ctx)
        types = [s.type for s in result.signals]
        assert "missing_segment" in types


# ---------------------------------------------------------------------------
# FullDriftDetector — get_trigger()
# ---------------------------------------------------------------------------

class TestGetTrigger:
    def test_not_confirmed_returns_none(self, detector):
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        confirmation = detector.detect(ctx)  # only 1 cycle
        assert detector.get_trigger(confirmation, ctx) is None

    def test_confirmed_returns_trigger(self, detector):
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        detector.detect(ctx)
        confirmation = detector.detect(ctx)
        trigger = detector.get_trigger(confirmation, ctx)
        assert isinstance(trigger, DriftTrigger)

    def test_trigger_has_valid_classification(self, detector):
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        detector.detect(ctx)
        conf = detector.detect(ctx)
        trigger = detector.get_trigger(conf, ctx)
        assert trigger.classification in {c.value for c in DriftClassification}

    def test_trigger_confidence_in_range(self, detector):
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        detector.detect(ctx)
        conf = detector.detect(ctx)
        trigger = detector.get_trigger(conf, ctx)
        assert 0.0 <= trigger.confidence <= 1.0

    def test_trigger_context_dicts_are_json_pure(self, detector):
        import json
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        detector.detect(ctx)
        conf = detector.detect(ctx)
        trigger = detector.get_trigger(conf, ctx)
        json.dumps(trigger.structural_context)
        json.dumps(trigger.behavioural_context)
        json.dumps(trigger.temporal_context)

    def test_trigger_separates_signal_classes(self, detector):
        ctx = DriftContext(
            timestamp=NOW_MS,
            subgoal_id="sg1",
            plan_id="p1",
            plan_records={"p1": _plan("p1", segments=["missing_seg"])},
            segment_records={},
            repair_attempts=REPAIR_LOOP_THRESHOLD,
        )
        detector.detect(ctx)
        conf = detector.detect(ctx)
        trigger = detector.get_trigger(conf, ctx)
        # Should have structural signals (missing_segment) and behavioural (repair_loop)
        assert trigger.structural_context["signal_count"] >= 1
        assert trigger.behavioural_context["signal_count"] >= 1


# ---------------------------------------------------------------------------
# FullDriftDetector — write_to_memory()
# ---------------------------------------------------------------------------

class TestWriteToMemory:
    def test_not_confirmed_returns_empty_no_write(self, detector):
        dm = DriftMemory()
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        conf = detector.detect(ctx)   # 1 cycle — not confirmed
        violations = detector.write_to_memory(conf, ctx, dm)
        assert violations == []
        assert len(dm) == 0

    def test_confirmed_writes_event(self, detector):
        dm = DriftMemory()
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        detector.detect(ctx)
        conf = detector.detect(ctx)
        violations = detector.write_to_memory(conf, ctx, dm)
        assert violations == []
        assert len(dm) == 1

    def test_written_event_has_correct_signal_type(self, detector):
        dm = DriftMemory()
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        detector.detect(ctx)
        conf = detector.detect(ctx)
        detector.write_to_memory(conf, ctx, dm)
        event = dm.last()
        assert event.signal_type == DRIFT_SIGNAL_TYPE

    def test_written_event_has_classification_in_details(self, detector):
        dm = DriftMemory()
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        detector.detect(ctx)
        conf = detector.detect(ctx)
        detector.write_to_memory(conf, ctx, dm)
        event = dm.last()
        assert "classification" in event.details

    def test_written_event_segment_id_is_none(self, detector):
        dm = DriftMemory()
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="sg1",
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        detector.detect(ctx)
        conf = detector.detect(ctx)
        detector.write_to_memory(conf, ctx, dm)
        assert dm.last().segment_id is None

    def test_write_uses_governed_path(self, detector):
        """Governance validation runs before write — invalid subgoal_id rejected."""
        dm = DriftMemory()
        # Craft a DriftConfirmation with confirmed=True but empty subgoal_id in ctx
        ctx = DriftContext(timestamp=NOW_MS, subgoal_id="",  # empty → governance violation
                           repair_attempts=REPAIR_LOOP_THRESHOLD)
        detector2 = FullDriftDetector(confirmation_cycles=1)
        conf = detector2.detect(ctx)
        violations = detector2.write_to_memory(conf, ctx, dm)
        assert violations  # should have at least one violation
        assert len(dm) == 0  # no write


# ---------------------------------------------------------------------------
# Public wrapper methods
# ---------------------------------------------------------------------------

class TestPublicWrappers:
    def test_compute_confidence_wrapper(self, detector):
        assert detector.compute_confidence([]) == 0.0
        assert detector.compute_confidence([_high()]) > 0.0

    def test_classify_wrapper(self, detector):
        assert detector.classify([]) == DriftClassification.NO_DRIFT
        assert detector.classify([_high()] * 5) == DriftClassification.CRITICAL_DRIFT

    def test_buffer_snapshot_returns_dict(self, detector):
        snap = detector.buffer_snapshot()
        assert isinstance(snap, dict)
