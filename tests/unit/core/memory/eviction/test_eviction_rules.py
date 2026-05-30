"""
Tests for EvictionRules — deterministic, pure, rule-based eviction decisions.
"""
from __future__ import annotations

import pytest
from typing import List, Optional

from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.memory.plan_memory_types import PlanMemoryRecord
from src.core.memory.drift_memory_types import DriftEvent
from src.core.memory.summarisation.summarisation_rules import SummarisationRules, _segment_list_fingerprint
from src.core.memory.eviction.eviction_rules import EvictionRules, _drift_event_id
from src.core.memory.eviction.eviction_types import (
    AccessRecord,
    EvictionDecision,
    EvictionReport,
    DriftEvictionReport,
    CompletionEvictionSummary,
)

NOW = 1_000_000


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rules() -> EvictionRules:
    return EvictionRules()


def make_access(record_id: str, record_type: str, access_count: int, last_accessed_at: int) -> AccessRecord:
    return AccessRecord(
        record_id=record_id,
        record_type=record_type,
        access_count=access_count,
        last_accessed_at=last_accessed_at,
    )


def make_segment(
    segment_id: str,
    subgoal_id: str = "sg-1",
    parent_id: Optional[str] = None,
    state: Optional[str] = None,
    created_at: str = "2024-01-01T00:00:00",
) -> SegmentMemoryRecord:
    return SegmentMemoryRecord(
        segment_id=segment_id,
        parent_id=parent_id,
        subgoal_id=subgoal_id,
        state=state,
        content=["step1"],
        created_at=created_at,
        context={},
        metadata={},
    )


def make_plan(
    plan_id: str,
    subgoal_id: str = "sg-1",
    segments: list = None,
) -> PlanMemoryRecord:
    return PlanMemoryRecord(
        plan_id=plan_id,
        subgoal_id=subgoal_id,
        segments=segments if segments is not None else [],
        created_at="2024-01-01T00:00:00",
        metadata={},
        intent="do something",
        targetskillid="skill-a",
        arguments={},
        reasoning_summary="",
    )


def make_subgoal(
    subgoal_id: str,
    parent_id: Optional[str] = None,
    state: str = "PENDING",
) -> SubgoalMemoryRecord:
    return SubgoalMemoryRecord(
        subgoal_id=subgoal_id,
        parent_id=parent_id,
        state=state,
        goal="do something",
        context={},
        metadata={},
        created_at=1000,
    )


def make_drift(
    subgoal_id: str = "sg-1",
    signal_type: str = "timeout",
    timestamp: int = 1000,
    segment_id: Optional[str] = None,
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
# compute_segment_refs
# ---------------------------------------------------------------------------

class TestComputeSegmentRefs:
    def test_no_refs(self, rules):
        segs = [make_segment("seg-a"), make_segment("seg-b")]
        assert rules.compute_segment_refs(segs, []) == set()

    def test_parent_id_protected(self, rules):
        segs = [make_segment("seg-a"), make_segment("seg-b", parent_id="seg-a")]
        refs = rules.compute_segment_refs(segs, [])
        assert "seg-a" in refs
        assert "seg-b" not in refs

    def test_plan_segments_protected(self, rules):
        segs = [make_segment("seg-a"), make_segment("seg-b")]
        plans = [make_plan("plan-1", segments=["seg-a"])]
        refs = rules.compute_segment_refs(segs, plans)
        assert "seg-a" in refs

    def test_combined_refs(self, rules):
        segs = [make_segment("seg-a"), make_segment("seg-b", parent_id="seg-a"), make_segment("seg-c")]
        plans = [make_plan("plan-1", segments=["seg-c"])]
        refs = rules.compute_segment_refs(segs, plans)
        assert refs == {"seg-a", "seg-c"}


# ---------------------------------------------------------------------------
# compute_subgoal_refs
# ---------------------------------------------------------------------------

class TestComputeSubgoalRefs:
    def test_no_refs(self, rules):
        sgs = [make_subgoal("sg-1")]
        assert rules.compute_subgoal_refs(sgs) == set()

    def test_parent_protected(self, rules):
        sgs = [make_subgoal("sg-1"), make_subgoal("sg-2", parent_id="sg-1")]
        refs = rules.compute_subgoal_refs(sgs)
        assert "sg-1" in refs


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------

class TestEvictLRU:
    def test_empty_log(self, rules):
        result = rules.evict_lru({}, set(), 5, NOW)
        assert isinstance(result, EvictionReport)
        assert result.eviction_count == 0
        assert result.decisions == ()
        assert result.reason == "LRU"

    def test_n_zero_returns_empty(self, rules):
        log = {"a": make_access("a", "segment", 5, 100)}
        result = rules.evict_lru(log, set(), 0, NOW)
        assert result.eviction_count == 0

    def test_n_negative_returns_empty(self, rules):
        log = {"a": make_access("a", "segment", 5, 100)}
        result = rules.evict_lru(log, set(), -1, NOW)
        assert result.eviction_count == 0

    def test_evicts_least_recently_accessed(self, rules):
        log = {
            "a": make_access("a", "segment", 5, 100),
            "b": make_access("b", "segment", 5, 200),
            "c": make_access("c", "segment", 5, 300),
        }
        result = rules.evict_lru(log, set(), 1, NOW)
        assert result.eviction_count == 1
        assert result.decisions[0].record_id == "a"

    def test_deterministic_sort_by_record_id_on_tie(self, rules):
        log = {
            "z": make_access("z", "segment", 1, 100),
            "a": make_access("a", "segment", 1, 100),
        }
        result = rules.evict_lru(log, set(), 1, NOW)
        assert result.decisions[0].record_id == "a"

    def test_protected_ids_excluded(self, rules):
        log = {
            "a": make_access("a", "segment", 1, 100),
            "b": make_access("b", "segment", 1, 200),
        }
        result = rules.evict_lru(log, {"a"}, 2, NOW)
        evicted_ids = {d.record_id for d in result.decisions}
        assert "a" not in evicted_ids
        assert "b" in evicted_ids

    def test_n_larger_than_candidates(self, rules):
        log = {
            "a": make_access("a", "segment", 1, 100),
            "b": make_access("b", "segment", 1, 200),
        }
        result = rules.evict_lru(log, set(), 99, NOW)
        assert result.eviction_count == 2

    def test_audit_fields_populated(self, rules):
        log = {"a": make_access("a", "segment", 3, 100)}
        result = rules.evict_lru(log, set(), 1, NOW)
        d = result.decisions[0]
        assert d.reason == "LRU"
        assert d.record_type == "segment"
        assert d.evicted_at == NOW
        assert d.details["last_accessed_at"] == 100
        assert d.details["access_count"] == 3


# ---------------------------------------------------------------------------
# LFU eviction
# ---------------------------------------------------------------------------

class TestEvictLFU:
    def test_empty_log(self, rules):
        result = rules.evict_lfu({}, set(), 5, NOW)
        assert result.eviction_count == 0
        assert result.reason == "LFU"

    def test_n_zero_returns_empty(self, rules):
        log = {"a": make_access("a", "segment", 5, 100)}
        result = rules.evict_lfu(log, set(), 0, NOW)
        assert result.eviction_count == 0

    def test_evicts_least_frequently_accessed(self, rules):
        log = {
            "a": make_access("a", "segment", 1, 300),
            "b": make_access("b", "segment", 10, 100),
            "c": make_access("c", "segment", 5, 200),
        }
        result = rules.evict_lfu(log, set(), 1, NOW)
        assert result.decisions[0].record_id == "a"

    def test_tie_broken_by_lru(self, rules):
        log = {
            "a": make_access("a", "segment", 3, 500),
            "b": make_access("b", "segment", 3, 100),
        }
        result = rules.evict_lfu(log, set(), 1, NOW)
        assert result.decisions[0].record_id == "b"

    def test_full_tie_broken_by_record_id(self, rules):
        log = {
            "z": make_access("z", "segment", 1, 100),
            "a": make_access("a", "segment", 1, 100),
        }
        result = rules.evict_lfu(log, set(), 1, NOW)
        assert result.decisions[0].record_id == "a"

    def test_protected_ids_excluded(self, rules):
        log = {
            "a": make_access("a", "segment", 1, 100),
            "b": make_access("b", "segment", 5, 100),
        }
        result = rules.evict_lfu(log, {"a"}, 2, NOW)
        evicted_ids = {d.record_id for d in result.decisions}
        assert "a" not in evicted_ids

    def test_audit_reason_is_lfu(self, rules):
        log = {"a": make_access("a", "segment", 2, 100)}
        result = rules.evict_lfu(log, set(), 1, NOW)
        assert result.decisions[0].reason == "LFU"
        assert "access_count" in result.decisions[0].details


# ---------------------------------------------------------------------------
# Drift-triggered eviction
# ---------------------------------------------------------------------------

class TestEvictByDrift:
    def test_empty_events(self, rules):
        result = rules.evict_by_drift([], 5, 1000, [], NOW)
        assert isinstance(result, DriftEvictionReport)
        assert result.evicted_drift_events == ()
        assert result.preserved_segment_id is None

    def test_single_event_never_evicted(self, rules):
        e = make_drift(timestamp=1000, segment_id="seg-a")
        result = rules.evict_by_drift([e], threshold_count=1, threshold_age_ms=0, signal_patterns=[], now=NOW)
        assert len(result.evicted_drift_events) == 0
        assert result.preserved_segment_id == "seg-a"

    def test_count_threshold_evicts_oldest(self, rules):
        events = [make_drift(timestamp=i * 100) for i in range(5)]
        result = rules.evict_by_drift(events, threshold_count=3, threshold_age_ms=0, signal_patterns=[], now=NOW)
        assert len(result.evicted_drift_events) == 2
        evicted_timestamps = {d.details["timestamp"] for d in result.evicted_drift_events}
        assert evicted_timestamps == {0, 100}

    def test_last_event_always_preserved(self, rules):
        events = [make_drift(timestamp=i * 100) for i in range(5)]
        result = rules.evict_by_drift(events, threshold_count=1, threshold_age_ms=0, signal_patterns=[], now=NOW)
        evicted_timestamps = {d.details["timestamp"] for d in result.evicted_drift_events}
        assert 400 not in evicted_timestamps

    def test_age_threshold_evicts_old_events(self, rules):
        old = make_drift(timestamp=NOW - 5000)
        recent = make_drift(timestamp=NOW - 100)
        result = rules.evict_by_drift(
            [old, recent], threshold_count=0, threshold_age_ms=1000, signal_patterns=[], now=NOW
        )
        evicted_timestamps = {d.details["timestamp"] for d in result.evicted_drift_events}
        assert (NOW - 5000) in evicted_timestamps
        assert (NOW - 100) not in evicted_timestamps

    def test_signal_pattern_evicts_matching(self, rules):
        e_timeout = make_drift(signal_type="timeout", timestamp=100)
        e_loop = make_drift(signal_type="loop", timestamp=200)
        e_last = make_drift(signal_type="timeout", timestamp=300)
        result = rules.evict_by_drift(
            [e_timeout, e_loop, e_last],
            threshold_count=0,
            threshold_age_ms=0,
            signal_patterns=["timeout"],
            now=NOW,
        )
        evicted_types = {d.details["signal_type"] for d in result.evicted_drift_events}
        assert "timeout" in evicted_types
        assert "loop" not in evicted_types

    def test_preserved_segment_id_from_last_event(self, rules):
        events = [
            make_drift(timestamp=100, segment_id="seg-a"),
            make_drift(timestamp=200, segment_id="seg-b"),
        ]
        result = rules.evict_by_drift(events, threshold_count=1, threshold_age_ms=0, signal_patterns=[], now=NOW)
        assert result.preserved_segment_id == "seg-b"

    def test_deterministic_across_calls(self, rules):
        events = [make_drift(timestamp=i * 100, signal_type=f"s{i}") for i in range(5)]
        r1 = rules.evict_by_drift(events, threshold_count=3, threshold_age_ms=0, signal_patterns=[], now=NOW)
        r2 = rules.evict_by_drift(events, threshold_count=3, threshold_age_ms=0, signal_patterns=[], now=NOW)
        assert r1 == r2

    def test_disabled_thresholds_no_eviction(self, rules):
        events = [make_drift(timestamp=i * 100) for i in range(10)]
        result = rules.evict_by_drift(
            events, threshold_count=0, threshold_age_ms=0, signal_patterns=[], now=NOW
        )
        assert result.evicted_drift_events == ()

    def test_audit_fields_populated(self, rules):
        old = make_drift(timestamp=100, signal_type="timeout")
        last = make_drift(timestamp=NOW)
        result = rules.evict_by_drift([old, last], threshold_count=1, threshold_age_ms=0, signal_patterns=[], now=NOW)
        assert len(result.evicted_drift_events) == 1
        d = result.evicted_drift_events[0]
        assert d.reason == "DRIFT"
        assert d.record_type == "drift_event"
        assert "age_ms" in d.details


# ---------------------------------------------------------------------------
# Subgoal-completion eviction
# ---------------------------------------------------------------------------

class TestEvictOnSubgoalCompletion:
    def test_basic_eviction(self, rules):
        segs = [make_segment("seg-a", subgoal_id="sg-1")]
        result = rules.evict_on_subgoal_completion("sg-1", segs, [], [], NOW)
        assert isinstance(result, CompletionEvictionSummary)
        assert result.subgoal_id == "sg-1"
        assert len(result.evicted_segments) == 1
        assert result.evicted_segments[0].record_id == "seg-a"

    def test_no_segments_for_subgoal(self, rules):
        segs = [make_segment("seg-a", subgoal_id="sg-2")]
        result = rules.evict_on_subgoal_completion("sg-1", segs, [], [], NOW)
        assert result.evicted_segments == ()

    def test_externally_referenced_segment_protected(self, rules):
        # seg-a belongs to sg-1 but is a parent of seg-b in sg-2 → must not be evicted
        seg_a = make_segment("seg-a", subgoal_id="sg-1")
        seg_b = make_segment("seg-b", subgoal_id="sg-2", parent_id="seg-a")
        result = rules.evict_on_subgoal_completion("sg-1", [seg_a, seg_b], [], [], NOW)
        evicted_ids = {d.record_id for d in result.evicted_segments}
        assert "seg-a" not in evicted_ids

    def test_ancestor_closure_protects_chain(self, rules):
        # seg-root → seg-mid → seg-leaf (all sg-1)
        # seg-other (sg-2) references seg-leaf as parent
        # → seg-leaf is externally protected → seg-mid and seg-root must also be retained
        seg_root = make_segment("seg-root", subgoal_id="sg-1")
        seg_mid = make_segment("seg-mid", subgoal_id="sg-1", parent_id="seg-root")
        seg_leaf = make_segment("seg-leaf", subgoal_id="sg-1", parent_id="seg-mid")
        seg_other = make_segment("seg-other", subgoal_id="sg-2", parent_id="seg-leaf")
        all_segs = [seg_root, seg_mid, seg_leaf, seg_other]
        result = rules.evict_on_subgoal_completion("sg-1", all_segs, [], [], NOW)
        evicted_ids = {d.record_id for d in result.evicted_segments}
        assert "seg-root" not in evicted_ids
        assert "seg-mid" not in evicted_ids
        assert "seg-leaf" not in evicted_ids

    def test_plan_ref_protects_segment(self, rules):
        seg = make_segment("seg-a", subgoal_id="sg-1")
        plan = make_plan("plan-other", subgoal_id="sg-2", segments=["seg-a"])
        result = rules.evict_on_subgoal_completion("sg-1", [seg], [], [plan], NOW)
        evicted_ids = {d.record_id for d in result.evicted_segments}
        assert "seg-a" not in evicted_ids

    def test_drift_events_evicted_with_segments(self, rules):
        seg = make_segment("seg-a", subgoal_id="sg-1")
        drift = make_drift(subgoal_id="sg-1", segment_id="seg-a", timestamp=1000)
        result = rules.evict_on_subgoal_completion("sg-1", [seg], [drift], [], NOW)
        assert len(result.evicted_drift_events) == 1

    def test_drift_events_not_evicted_for_protected_segments(self, rules):
        seg_a = make_segment("seg-a", subgoal_id="sg-1")
        seg_b = make_segment("seg-b", subgoal_id="sg-2", parent_id="seg-a")
        drift = make_drift(subgoal_id="sg-1", segment_id="seg-a", timestamp=1000)
        result = rules.evict_on_subgoal_completion("sg-1", [seg_a, seg_b], [drift], [], NOW)
        assert result.evicted_drift_events == ()

    def test_plan_evicted_when_all_segments_safe(self, rules):
        seg = make_segment("seg-a", subgoal_id="sg-1")
        plan = make_plan("plan-1", subgoal_id="sg-1", segments=["seg-a"])
        result = rules.evict_on_subgoal_completion("sg-1", [seg], [], [plan], NOW, evict_plan=True)
        assert any(d.record_id == "plan-1" for d in result.evicted_plans)

    def test_plan_not_evicted_when_segment_retained(self, rules):
        seg_a = make_segment("seg-a", subgoal_id="sg-1")
        seg_b = make_segment("seg-b", subgoal_id="sg-2", parent_id="seg-a")
        plan = make_plan("plan-1", subgoal_id="sg-1", segments=["seg-a"])
        result = rules.evict_on_subgoal_completion("sg-1", [seg_a, seg_b], [], [plan], NOW, evict_plan=True)
        assert result.evicted_plans == ()

    def test_evict_plan_false_skips_plans(self, rules):
        seg = make_segment("seg-a", subgoal_id="sg-1")
        plan = make_plan("plan-1", subgoal_id="sg-1", segments=["seg-a"])
        result = rules.evict_on_subgoal_completion("sg-1", [seg], [], [plan], NOW, evict_plan=False)
        assert result.evicted_plans == ()

    def test_reason_is_subgoal_complete(self, rules):
        seg = make_segment("seg-a", subgoal_id="sg-1")
        result = rules.evict_on_subgoal_completion("sg-1", [seg], [], [], NOW)
        assert all(d.reason == "SUBGOAL_COMPLETE" for d in result.evicted_segments)

    def test_deterministic(self, rules):
        segs = [make_segment(f"seg-{i}", subgoal_id="sg-1") for i in range(5)]
        r1 = rules.evict_on_subgoal_completion("sg-1", segs, [], [], NOW)
        r2 = rules.evict_on_subgoal_completion("sg-1", segs, [], [], NOW)
        assert r1 == r2


# ---------------------------------------------------------------------------
# Summary-state replacement
# ---------------------------------------------------------------------------

class TestEvictBySummaryReplacement:
    def _make_summary_meta(self, records):
        sr = SummarisationRules()
        summary = sr.summarise_segment_list(records, NOW)
        sorted_records = sorted(records, key=lambda r: (r.created_at, r.segment_id))
        fp = _segment_list_fingerprint(sorted_records)
        return summary.meta, fp

    def test_fresh_summary_evicts_unprotected(self, rules):
        records = [make_segment("seg-a"), make_segment("seg-b")]
        meta, fp = self._make_summary_meta(records)
        result = rules.evict_by_summary_replacement(records, meta, fp, set(), NOW)
        assert result.eviction_count == 2
        assert result.reason == "SUMMARY_REPLACEMENT"

    def test_stale_summary_evicts_nothing(self, rules):
        records = [make_segment("seg-a")]
        meta, _ = self._make_summary_meta(records)
        result = rules.evict_by_summary_replacement(records, meta, "wrong-fingerprint", set(), NOW)
        assert result.eviction_count == 0

    def test_stale_by_count_change(self, rules):
        records = [make_segment("seg-a")]
        meta, fp = self._make_summary_meta(records)
        records_grown = [make_segment("seg-a"), make_segment("seg-b")]
        result = rules.evict_by_summary_replacement(records_grown, meta, fp, set(), NOW)
        assert result.eviction_count == 0

    def test_protected_ids_excluded(self, rules):
        records = [make_segment("seg-a"), make_segment("seg-b")]
        meta, fp = self._make_summary_meta(records)
        result = rules.evict_by_summary_replacement(records, meta, fp, {"seg-a"}, NOW)
        evicted_ids = {d.record_id for d in result.decisions}
        assert "seg-a" not in evicted_ids
        assert "seg-b" in evicted_ids

    def test_all_protected_evicts_nothing(self, rules):
        records = [make_segment("seg-a")]
        meta, fp = self._make_summary_meta(records)
        result = rules.evict_by_summary_replacement(records, meta, fp, {"seg-a"}, NOW)
        assert result.eviction_count == 0

    def test_audit_includes_fingerprint(self, rules):
        records = [make_segment("seg-a")]
        meta, fp = self._make_summary_meta(records)
        result = rules.evict_by_summary_replacement(records, meta, fp, set(), NOW)
        assert result.decisions[0].details["summary_fingerprint"] == fp

    def test_reason_is_summary_replacement(self, rules):
        records = [make_segment("seg-a")]
        meta, fp = self._make_summary_meta(records)
        result = rules.evict_by_summary_replacement(records, meta, fp, set(), NOW)
        assert result.decisions[0].reason == "SUMMARY_REPLACEMENT"


# ---------------------------------------------------------------------------
# Ancestor closure
# ---------------------------------------------------------------------------

class TestAncestorClosure:
    def test_no_parents(self, rules):
        segs = {s.segment_id: s for s in [make_segment("seg-a")]}
        closure = rules._ancestor_closure({"seg-a"}, segs)
        assert closure == {"seg-a"}

    def test_single_parent(self, rules):
        seg_root = make_segment("seg-root")
        seg_child = make_segment("seg-child", parent_id="seg-root")
        segs = {s.segment_id: s for s in [seg_root, seg_child]}
        closure = rules._ancestor_closure({"seg-child"}, segs)
        assert "seg-root" in closure
        assert "seg-child" in closure

    def test_deep_chain(self, rules):
        segs_list = [make_segment(f"seg-{i}", parent_id=f"seg-{i-1}" if i > 0 else None) for i in range(5)]
        segs = {s.segment_id: s for s in segs_list}
        closure = rules._ancestor_closure({"seg-4"}, segs)
        assert closure == {"seg-0", "seg-1", "seg-2", "seg-3", "seg-4"}

    def test_missing_parent_stops_traversal(self, rules):
        seg = make_segment("seg-a", parent_id="missing-parent")
        segs = {"seg-a": seg}
        closure = rules._ancestor_closure({"seg-a"}, segs)
        assert "missing-parent" not in closure

    def test_empty_seed(self, rules):
        segs = {s.segment_id: s for s in [make_segment("seg-a")]}
        closure = rules._ancestor_closure(set(), segs)
        assert closure == set()


# ---------------------------------------------------------------------------
# Drift event ID helper
# ---------------------------------------------------------------------------

class TestDriftEventId:
    def test_returns_string(self):
        e = make_drift()
        assert isinstance(_drift_event_id(0, e), str)

    def test_different_ordinals_produce_different_ids(self):
        e = make_drift()
        assert _drift_event_id(0, e) != _drift_event_id(1, e)

    def test_stable_across_calls(self):
        e = make_drift(timestamp=1234, signal_type="loop")
        assert _drift_event_id(0, e) == _drift_event_id(0, e)

    def test_different_events_different_ids(self):
        e1 = make_drift(signal_type="timeout", timestamp=100)
        e2 = make_drift(signal_type="loop", timestamp=100)
        assert _drift_event_id(0, e1) != _drift_event_id(0, e2)
