"""
Tests for SummarisationRules and related types.

All summarisation is deterministic, rule-based, and structural.
No LLM calls, no semantic inference.
"""
from __future__ import annotations

import pytest
from typing import List

from src.strategy.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.strategy.memory.segment_memory_types import SegmentMemoryRecord
from src.strategy.memory.plan_memory_types import PlanMemoryRecord
from src.strategy.memory.drift_memory_types import DriftEvent
from src.strategy.memory.summarisation.summarisation_rules import (
    SummarisationRules,
    _segment_list_fingerprint,
    _subgoal_chain_fingerprint,
    _plan_fingerprint,
    _segment_chain_fingerprint,
    _drift_fingerprint,
)
from src.strategy.memory.summarisation.summary_types import (
    SummaryMetadata,
    SegmentListSummary,
    SubgoalChainSummary,
    PlanSummary,
    SegmentChainSummary,
    DriftSummary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = 1_000_000


def make_subgoal_record(
    subgoal_id: str,
    parent_id=None,
    state: str = "PENDING",
    goal: str = "do something",
    created_at: int = 1000,
) -> SubgoalMemoryRecord:
    return SubgoalMemoryRecord(
        subgoal_id=subgoal_id,
        parent_id=parent_id,
        state=state,
        goal=goal,
        context={},
        metadata={},
        created_at=created_at,
    )


def make_segment_record(
    segment_id: str,
    subgoal_id: str = "sg-1",
    parent_id=None,
    state=None,
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


def make_plan_record(
    plan_id: str = "plan-1",
    subgoal_id: str = "sg-1",
    segments: list = None,
    created_at: str = "2024-01-01T00:00:00",
    metadata: dict = None,
) -> PlanMemoryRecord:
    return PlanMemoryRecord(
        plan_id=plan_id,
        subgoal_id=subgoal_id,
        segments=segments if segments is not None else ["seg-1", "seg-2"],
        created_at=created_at,
        metadata=metadata if metadata is not None else {},
        intent="do something",
        targetskillid="skill-a",
        arguments={},
        reasoning_summary="",
    )


def make_drift_event(
    subgoal_id: str = "sg-1",
    signal_type: str = "timeout",
    timestamp: int = 1000,
    confidence: float = 0.8,
    segment_id=None,
    step_id=None,
) -> DriftEvent:
    return DriftEvent(
        timestamp=timestamp,
        subgoal_id=subgoal_id,
        segment_id=segment_id,
        step_id=step_id,
        signal_type=signal_type,
        confidence=confidence,
        details={},
    )


@pytest.fixture
def rules() -> SummarisationRules:
    return SummarisationRules()


# ---------------------------------------------------------------------------
# SegmentListSummary
# ---------------------------------------------------------------------------

class TestSummariseSegmentList:
    def test_empty(self, rules):
        result = rules.summarise_segment_list([], NOW)
        assert isinstance(result, SegmentListSummary)
        assert result.count == 0
        assert result.first_id is None
        assert result.last_id is None
        assert result.meta.source_count == 0

    def test_single(self, rules):
        r = make_segment_record("seg-a", created_at="2024-01-01T00:00:00")
        result = rules.summarise_segment_list([r], NOW)
        assert result.count == 1
        assert result.first_id == "seg-a"
        assert result.last_id == "seg-a"

    def test_multiple_ordered_by_created_at(self, rules):
        r1 = make_segment_record("seg-b", created_at="2024-01-02T00:00:00")
        r2 = make_segment_record("seg-a", created_at="2024-01-01T00:00:00")
        result = rules.summarise_segment_list([r1, r2], NOW)
        assert result.first_id == "seg-a"
        assert result.last_id == "seg-b"
        assert result.count == 2

    def test_tie_broken_by_segment_id(self, rules):
        r1 = make_segment_record("seg-z", created_at="2024-01-01T00:00:00")
        r2 = make_segment_record("seg-a", created_at="2024-01-01T00:00:00")
        result = rules.summarise_segment_list([r1, r2], NOW)
        assert result.first_id == "seg-a"
        assert result.last_id == "seg-z"

    def test_metadata_generated_at(self, rules):
        r = make_segment_record("seg-a")
        result = rules.summarise_segment_list([r], NOW)
        assert result.meta.generated_at == NOW

    def test_deterministic_given_same_input(self, rules):
        records = [
            make_segment_record("seg-c", created_at="2024-01-03T00:00:00"),
            make_segment_record("seg-a", created_at="2024-01-01T00:00:00"),
            make_segment_record("seg-b", created_at="2024-01-02T00:00:00"),
        ]
        r1 = rules.summarise_segment_list(records, NOW)
        r2 = rules.summarise_segment_list(records, NOW)
        assert r1 == r2


# ---------------------------------------------------------------------------
# SubgoalChainSummary
# ---------------------------------------------------------------------------

class TestSummariseSubgoalChain:
    def test_empty(self, rules):
        result = rules.summarise_subgoal_chain([], NOW)
        assert isinstance(result, SubgoalChainSummary)
        assert result.depth == 0
        assert result.root_id is None
        assert result.leaf_id is None

    def test_single(self, rules):
        r = make_subgoal_record("sg-root")
        result = rules.summarise_subgoal_chain([r], NOW)
        assert result.depth == 1
        assert result.root_id == "sg-root"
        assert result.leaf_id == "sg-root"

    def test_chain(self, rules):
        root = make_subgoal_record("sg-1")
        mid = make_subgoal_record("sg-2", parent_id="sg-1")
        leaf = make_subgoal_record("sg-3", parent_id="sg-2")
        result = rules.summarise_subgoal_chain([root, mid, leaf], NOW)
        assert result.depth == 3
        assert result.root_id == "sg-1"
        assert result.leaf_id == "sg-3"

    def test_deterministic(self, rules):
        records = [make_subgoal_record(f"sg-{i}", parent_id=f"sg-{i-1}" if i else None) for i in range(5)]
        assert rules.summarise_subgoal_chain(records, NOW) == rules.summarise_subgoal_chain(records, NOW)


# ---------------------------------------------------------------------------
# PlanSummary
# ---------------------------------------------------------------------------

class TestSummarisePlan:
    def test_basic(self, rules):
        record = make_plan_record(segments=["s1", "s2", "s3"])
        result = rules.summarise_plan(record, NOW)
        assert isinstance(result, PlanSummary)
        assert result.segment_count == 3
        assert result.created_at == "2024-01-01T00:00:00"
        assert result.has_metadata is False

    def test_has_metadata_true(self, rules):
        record = make_plan_record(metadata={"key": "value"})
        result = rules.summarise_plan(record, NOW)
        assert result.has_metadata is True

    def test_empty_segments(self, rules):
        record = make_plan_record(segments=[])
        result = rules.summarise_plan(record, NOW)
        assert result.segment_count == 0

    def test_deterministic(self, rules):
        record = make_plan_record()
        assert rules.summarise_plan(record, NOW) == rules.summarise_plan(record, NOW)

    def test_meta_source_count_is_one(self, rules):
        record = make_plan_record()
        result = rules.summarise_plan(record, NOW)
        assert result.meta.source_count == 1


# ---------------------------------------------------------------------------
# SegmentChainSummary
# ---------------------------------------------------------------------------

class TestSummariseSegmentChain:
    def test_empty(self, rules):
        result = rules.summarise_segment_chain([], NOW)
        assert isinstance(result, SegmentChainSummary)
        assert result.chain_length == 0
        assert result.terminal_state == "pending"

    def test_state_none_defaults_to_pending(self, rules):
        r = make_segment_record("seg-a", state=None)
        result = rules.summarise_segment_chain([r], NOW)
        assert result.terminal_state == "pending"

    def test_state_used_when_not_none(self, rules):
        r = make_segment_record("seg-a", state="complete")
        result = rules.summarise_segment_chain([r], NOW)
        assert result.terminal_state == "complete"

    def test_chain_length(self, rules):
        records = [make_segment_record(f"seg-{i}") for i in range(4)]
        result = rules.summarise_segment_chain(records, NOW)
        assert result.chain_length == 4

    def test_terminal_state_from_last_record(self, rules):
        records = [
            make_segment_record("seg-0", state="complete"),
            make_segment_record("seg-1", state=None),
        ]
        result = rules.summarise_segment_chain(records, NOW)
        assert result.terminal_state == "pending"

    def test_deterministic(self, rules):
        records = [make_segment_record(f"seg-{i}") for i in range(3)]
        assert rules.summarise_segment_chain(records, NOW) == rules.summarise_segment_chain(records, NOW)


# ---------------------------------------------------------------------------
# DriftSummary
# ---------------------------------------------------------------------------

class TestSummariseDrift:
    def test_empty(self, rules):
        result = rules.summarise_drift([], NOW)
        assert isinstance(result, DriftSummary)
        assert result.drift_events == 0
        assert result.last_drift_at is None
        assert result.signal_type_counts == {}

    def test_single_event(self, rules):
        e = make_drift_event(signal_type="timeout", timestamp=5000)
        result = rules.summarise_drift([e], NOW)
        assert result.drift_events == 1
        assert result.last_drift_at == 5000
        assert result.signal_type_counts == {"timeout": 1}

    def test_multiple_signal_types(self, rules):
        events = [
            make_drift_event(signal_type="timeout", timestamp=1000),
            make_drift_event(signal_type="loop", timestamp=2000),
            make_drift_event(signal_type="timeout", timestamp=3000),
        ]
        result = rules.summarise_drift(events, NOW)
        assert result.drift_events == 3
        assert result.last_drift_at == 3000
        assert result.signal_type_counts == {"loop": 1, "timeout": 2}

    def test_signal_type_counts_sorted_keys(self, rules):
        events = [
            make_drift_event(signal_type="z-signal"),
            make_drift_event(signal_type="a-signal"),
            make_drift_event(signal_type="m-signal"),
        ]
        result = rules.summarise_drift(events, NOW)
        assert list(result.signal_type_counts.keys()) == ["a-signal", "m-signal", "z-signal"]

    def test_last_drift_at_is_max_timestamp(self, rules):
        events = [
            make_drift_event(timestamp=500),
            make_drift_event(timestamp=9999),
            make_drift_event(timestamp=100),
        ]
        result = rules.summarise_drift(events, NOW)
        assert result.last_drift_at == 9999

    def test_deterministic(self, rules):
        events = [make_drift_event(signal_type=f"sig-{i}", timestamp=i * 100) for i in range(5)]
        assert rules.summarise_drift(events, NOW) == rules.summarise_drift(events, NOW)


# ---------------------------------------------------------------------------
# Staleness detection
# ---------------------------------------------------------------------------

class TestIsStale:
    def test_fresh_summary_not_stale(self, rules):
        records = [make_segment_record("seg-a")]
        summary = rules.summarise_segment_list(records, NOW)
        fp = _segment_list_fingerprint(
            sorted(records, key=lambda r: (r.created_at, r.segment_id))
        )
        assert not rules.is_stale(summary.meta, current_count=1, current_fingerprint=fp)

    def test_stale_when_count_changes(self, rules):
        records = [make_segment_record("seg-a")]
        summary = rules.summarise_segment_list(records, NOW)
        assert rules.is_stale(summary.meta, current_count=2, current_fingerprint=summary.meta.source_fingerprint)

    def test_stale_when_fingerprint_changes(self, rules):
        records = [make_segment_record("seg-a")]
        summary = rules.summarise_segment_list(records, NOW)
        assert rules.is_stale(summary.meta, current_count=1, current_fingerprint="different-hash")

    def test_stale_when_content_changes_same_count(self, rules):
        r1 = make_segment_record("seg-a", created_at="2024-01-01T00:00:00")
        summary = rules.summarise_segment_list([r1], NOW)
        r2 = make_segment_record("seg-b", created_at="2024-01-01T00:00:00")
        fp2 = _segment_list_fingerprint([r2])
        assert rules.is_stale(summary.meta, current_count=1, current_fingerprint=fp2)

    def test_stale_when_order_changes_chain(self, rules):
        r1 = make_subgoal_record("sg-1")
        r2 = make_subgoal_record("sg-2", parent_id="sg-1")
        summary = rules.summarise_subgoal_chain([r1, r2], NOW)
        fp_reversed = _subgoal_chain_fingerprint([r2, r1])
        assert rules.is_stale(summary.meta, current_count=2, current_fingerprint=fp_reversed)


# ---------------------------------------------------------------------------
# SummaryMetadata
# ---------------------------------------------------------------------------

class TestSummaryMetadata:
    def test_frozen(self, rules):
        record = make_segment_record("seg-a")
        summary = rules.summarise_segment_list([record], NOW)
        with pytest.raises((AttributeError, TypeError)):
            summary.meta.source_count = 99  # type: ignore

    def test_fingerprint_is_string(self, rules):
        record = make_segment_record("seg-a")
        summary = rules.summarise_segment_list([record], NOW)
        assert isinstance(summary.meta.source_fingerprint, str)
        assert len(summary.meta.source_fingerprint) > 0


# ---------------------------------------------------------------------------
# DriftSummary mutability guard
# ---------------------------------------------------------------------------

class TestDriftSummaryMutability:
    def test_signal_type_counts_is_deep_copied(self, rules):
        events = [make_drift_event(signal_type="timeout")]
        result = rules.summarise_drift(events, NOW)
        # External modification of the returned dict should not affect the stored copy
        # (frozen dataclass ensures field reassignment is blocked; post_init deepcopies)
        original_count = result.signal_type_counts.get("timeout")
        # Attempt mutation via the returned reference
        result.signal_type_counts["timeout"] = 999
        # Create another summary from the same events to confirm state unchanged
        result2 = rules.summarise_drift(events, NOW)
        assert result2.signal_type_counts.get("timeout") == original_count


# ---------------------------------------------------------------------------
# Fingerprint helpers — determinism and collision resistance
# ---------------------------------------------------------------------------

class TestFingerprintHelpers:
    def test_segment_list_fingerprint_stable(self):
        records = [make_segment_record("seg-a"), make_segment_record("seg-b")]
        assert _segment_list_fingerprint(records) == _segment_list_fingerprint(records)

    def test_segment_list_fingerprint_different_for_different_records(self):
        r1 = [make_segment_record("seg-a")]
        r2 = [make_segment_record("seg-b")]
        assert _segment_list_fingerprint(r1) != _segment_list_fingerprint(r2)

    def test_subgoal_chain_fingerprint_sensitive_to_state(self):
        r_pending = make_subgoal_record("sg-1", state="PENDING")
        r_active = make_subgoal_record("sg-1", state="ACTIVE")
        assert _subgoal_chain_fingerprint([r_pending]) != _subgoal_chain_fingerprint([r_active])

    def test_plan_fingerprint_sensitive_to_segment_count(self):
        r1 = make_plan_record(segments=["s1"])
        r2 = make_plan_record(segments=["s1", "s2"])
        assert _plan_fingerprint(r1) != _plan_fingerprint(r2)

    def test_plan_fingerprint_sensitive_to_metadata_presence(self):
        r_no_meta = make_plan_record(metadata={})
        r_with_meta = make_plan_record(metadata={"k": "v"})
        assert _plan_fingerprint(r_no_meta) != _plan_fingerprint(r_with_meta)

    def test_drift_fingerprint_sensitive_to_signal_type(self):
        e1 = [make_drift_event(signal_type="timeout")]
        e2 = [make_drift_event(signal_type="loop")]
        assert _drift_fingerprint(e1) != _drift_fingerprint(e2)

    def test_drift_fingerprint_sensitive_to_event_order(self):
        e1 = make_drift_event(signal_type="a", timestamp=100)
        e2 = make_drift_event(signal_type="b", timestamp=200)
        assert _drift_fingerprint([e1, e2]) != _drift_fingerprint([e2, e1])

    def test_drift_fingerprint_stable_across_calls(self):
        events = [make_drift_event(timestamp=i * 100, signal_type=f"s{i}") for i in range(3)]
        assert _drift_fingerprint(events) == _drift_fingerprint(events)

    def test_segment_chain_fingerprint_sensitive_to_state(self):
        r_none = make_segment_record("seg-a", state=None)
        r_complete = make_segment_record("seg-a", state="complete")
        assert _segment_chain_fingerprint([r_none]) != _segment_chain_fingerprint([r_complete])