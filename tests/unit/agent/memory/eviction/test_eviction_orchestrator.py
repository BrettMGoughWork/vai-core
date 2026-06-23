"""
Tests for EvictionOrchestrator — verifies wiring between EvictionRules and memory stores.

Focuses on:
- Correct snapshot → rule → apply flow for each trigger point.
- Proper delegation to each store's remove / remove_events API.
- Edge cases (empty stores, no-op evictions, drift event matching).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
from unittest import mock

import pytest

from src.agent.memory.drift_memory_types import DriftEvent
from src.agent.memory.eviction.eviction_orchestrator import EvictionOrchestrator
from src.agent.memory.eviction.eviction_types import (
    CompletionEvictionSummary,
    EvictionDecision,
)
from src.agent.memory.plan_memory_types import PlanMemoryRecord, PlanMemorySnapshot
from src.agent.memory.segment_memory_types import (
    SegmentMemoryRecord,
    SegmentMemorySnapshot,
)
from src.agent.memory.subgoal_memory_types import SubgoalMemoryRecord


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

NOW = 1_000_000


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
    intent: str = "do something",
    segments: Optional[Tuple[str, ...]] = None,
) -> PlanMemoryRecord:
    return PlanMemoryRecord(
        plan_id=plan_id,
        subgoal_id=subgoal_id,
        intent=intent,
        segments=segments if segments is not None else (),
        created_at="2024-01-01T00:00:00",
        metadata={},
        targetskillid="skill-a",
        arguments={},
        reasoning_summary="",
    )


def make_drift(
    timestamp: int = 300,
    subgoal_id: str = "sg-1",
    segment_id: Optional[str] = None,
    signal_type: str = "pattern_deviation",
    confidence: float = 0.8,
) -> DriftEvent:
    return DriftEvent(
        timestamp=timestamp,
        subgoal_id=subgoal_id,
        segment_id=segment_id,
        step_id=None,
        signal_type=signal_type,
        confidence=confidence,
        details={},
    )


def make_decision(
    record_id: str,
    record_type: str = "segment",
    reason: str = "SUBGOAL_COMPLETE",
    details: Optional[dict] = None,
) -> EvictionDecision:
    return EvictionDecision(
        record_id=record_id,
        record_type=record_type,
        reason=reason,
        evicted_at=NOW,
        details=details or {},
    )


# ---------------------------------------------------------------------------
# Fixtures — mock stores
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_segment_memory():
    return mock.MagicMock()


@pytest.fixture
def mock_subgoal_memory():
    return mock.MagicMock()


@pytest.fixture
def mock_plan_memory():
    return mock.MagicMock()


@pytest.fixture
def mock_drift_memory():
    return mock.MagicMock()


@pytest.fixture
def mock_rules():
    return mock.MagicMock()


@pytest.fixture
def orchestrator(mock_segment_memory, mock_subgoal_memory, mock_plan_memory, mock_drift_memory, mock_rules):
    return EvictionOrchestrator(
        segment_memory=mock_segment_memory,
        subgoal_memory=mock_subgoal_memory,
        plan_memory=mock_plan_memory,
        drift_memory=mock_drift_memory,
        eviction_rules=mock_rules,
    )


# ---------------------------------------------------------------------------
# Tests: on_subgoal_completed
# ---------------------------------------------------------------------------


class TestOnSubgoalCompleted:
    """Verifies the subgoal-completion trigger snapshots stores and applies decisions."""

    def test_snapshots_and_applies(self, orchestrator, mock_rules):
        """Happy path: snapshots all three record stores and applies decisions."""
        seg = make_segment("seg-1")
        drift = make_drift()
        plan = make_plan("plan-1")

        # Stub snapshots
        orchestrator._segment_memory.snapshot.return_value = SegmentMemorySnapshot(records=(seg,))
        orchestrator._drift_memory.snapshot.return_value = mock.MagicMock(events=(drift,))
        orchestrator._plan_memory.snapshot.return_value = PlanMemorySnapshot(records=(plan,))

        seg_dec = make_decision("seg-1", "segment")
        drift_dec = make_decision("drift_0", "drift_event")
        plan_dec = make_decision("plan-1", "plan")

        mock_rules.evict_on_subgoal_completion.return_value = CompletionEvictionSummary(
            subgoal_id="sg-1",
            evicted_segments=(seg_dec,),
            evicted_drift_events=(drift_dec,),
            evicted_plans=(plan_dec,),
            generated_at=NOW,
        )

        summary = orchestrator.on_subgoal_completed("sg-1", now=NOW)

        mock_rules.evict_on_subgoal_completion.assert_called_once()
        call_kwargs = mock_rules.evict_on_subgoal_completion.call_args[1]
        assert call_kwargs["subgoal_id"] == "sg-1"

        # Decisions applied
        orchestrator._segment_memory.remove.assert_called_once_with(["seg-1"])
        orchestrator._plan_memory.remove.assert_called_once_with(["plan-1"])
        orchestrator._drift_memory.remove_events.assert_called_once()

        assert summary.subgoal_id == "sg-1"

    def test_no_decisions_no_calls_to_remove(self, orchestrator, mock_rules):
        """When eviction returns empty tuples, remove is called with empty lists but remove_events skipped."""
        seg = make_segment("seg-1")
        orchestrator._segment_memory.snapshot.return_value = SegmentMemorySnapshot(records=(seg,))
        orchestrator._drift_memory.snapshot.return_value = mock.MagicMock(events=())
        orchestrator._plan_memory.snapshot.return_value = PlanMemorySnapshot(records=())

        mock_rules.evict_on_subgoal_completion.return_value = CompletionEvictionSummary(
            subgoal_id="sg-1",
            evicted_segments=(),
            evicted_drift_events=(),
            evicted_plans=(),
            generated_at=NOW,
        )

        orchestrator.on_subgoal_completed("sg-1", now=NOW)

        orchestrator._segment_memory.remove.assert_called_once_with([])
        orchestrator._plan_memory.remove.assert_called_once_with([])
        # _remove_drift_by_decisions short-circuits on empty decisions
        orchestrator._drift_memory.remove_events.assert_not_called()

    def test_uses_default_now_when_not_provided(self, orchestrator, mock_rules):
        """When now is None, the orchestrator generates a timestamp."""
        orchestrator._segment_memory.snapshot.return_value = SegmentMemorySnapshot(records=())
        orchestrator._drift_memory.snapshot.return_value = mock.MagicMock(events=())
        orchestrator._plan_memory.snapshot.return_value = PlanMemorySnapshot(records=())

        mock_rules.evict_on_subgoal_completion.return_value = CompletionEvictionSummary(
            subgoal_id="sg-1",
            evicted_segments=(),
            evicted_drift_events=(),
            evicted_plans=(),
            generated_at=0,
        )

        orchestrator.on_subgoal_completed("sg-1")

        # now was passed to the rules call — can't predict ms value, just check it's > 0
        call_kwargs = mock_rules.evict_on_subgoal_completion.call_args[1]
        assert call_kwargs["now"] > 0

    def test_evict_plan_flag_passthrough(self, orchestrator, mock_rules):
        """The evict_plan flag is forwarded to EvictionRules."""
        orchestrator._segment_memory.snapshot.return_value = SegmentMemorySnapshot(records=())
        orchestrator._drift_memory.snapshot.return_value = mock.MagicMock(events=())
        orchestrator._plan_memory.snapshot.return_value = PlanMemorySnapshot(records=())

        mock_rules.evict_on_subgoal_completion.return_value = CompletionEvictionSummary(
            subgoal_id="sg-1",
            evicted_segments=(),
            evicted_drift_events=(),
            evicted_plans=(),
            generated_at=NOW,
        )

        orchestrator.on_subgoal_completed("sg-1", now=NOW, evict_plan=True)

        call_kwargs = mock_rules.evict_on_subgoal_completion.call_args[1]
        assert call_kwargs["evict_plan"] is True


# ---------------------------------------------------------------------------
# Tests: on_drift_overflow
# ---------------------------------------------------------------------------


class TestOnDriftOverflow:
    """Verifies the drift-overflow trigger snapshots and applies drift eviction."""

    def test_evicts_drift_events(self, orchestrator, mock_rules):
        """Happy path: drift events are evicted via remove_events."""
        d1 = make_drift(timestamp=100, subgoal_id="sg-1")
        d2 = make_drift(timestamp=200, subgoal_id="sg-2")

        orchestrator._drift_memory.snapshot.return_value = mock.MagicMock(events=(d1, d2))

        mock_rules.evict_by_drift.return_value = mock.MagicMock(
            evicted_drift_events=(make_decision("drift_0", "drift_event"),),
        )

        orchestrator.on_drift_overflow(now=NOW)

        mock_rules.evict_by_drift.assert_called_once()
        orchestrator._drift_memory.remove_events.assert_called_once()

    def test_no_eviction_decisions_skips_remove(self, orchestrator, mock_rules):
        """When evict_by_drift returns no decisions, remove_events is not called."""
        orchestrator._drift_memory.snapshot.return_value = mock.MagicMock(events=())

        mock_rules.evict_by_drift.return_value = mock.MagicMock(evicted_drift_events=())

        orchestrator.on_drift_overflow(now=NOW)

        orchestrator._drift_memory.remove_events.assert_not_called()

    def test_passes_threshold_and_signal_args(self, orchestrator, mock_rules):
        """Threshold count, age, and signal patterns are forwarded."""
        orchestrator._drift_memory.snapshot.return_value = mock.MagicMock(events=())
        mock_rules.evict_by_drift.return_value = mock.MagicMock(evicted_drift_events=())

        orchestrator.on_drift_overflow(
            now=NOW,
            threshold_count=10,
            threshold_age_ms=5000,
            signal_patterns=["pattern_deviation"],
        )

        call_kwargs = mock_rules.evict_by_drift.call_args[1]
        assert call_kwargs["threshold_count"] == 10
        assert call_kwargs["threshold_age_ms"] == 5000
        assert call_kwargs["signal_patterns"] == ["pattern_deviation"]


# ---------------------------------------------------------------------------
# Tests: on_episode_compacted
# ---------------------------------------------------------------------------


class TestOnEpisodeCompacted:
    """Placeholder — currently a no-op."""

    def test_no_op(self, orchestrator):
        """Currently does nothing; no stores are touched."""
        orchestrator.on_episode_compacted()

        orchestrator._segment_memory.remove.assert_not_called()
        orchestrator._subgoal_memory.remove.assert_not_called()
        orchestrator._plan_memory.remove.assert_not_called()
        orchestrator._drift_memory.remove_events.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    """Verifies default EvictionRules is created when none is provided."""

    def test_default_rules_created(self):
        """When eviction_rules is None, a new EvictionRules is instantiated."""
        from src.agent.memory.eviction.eviction_rules import EvictionRules

        orch = EvictionOrchestrator(
            segment_memory=mock.MagicMock(),
            subgoal_memory=mock.MagicMock(),
            plan_memory=mock.MagicMock(),
            drift_memory=mock.MagicMock(),
        )
        assert isinstance(orch._eviction_rules, EvictionRules)


# ---------------------------------------------------------------------------
# Integration-ish: _remove_drift_by_decisions with real DriftEvent objects
# ---------------------------------------------------------------------------


class TestRemoveDriftByDecisions:
    """Verifies the internal helper correctly maps decisions to DriftEvent objects."""

    def test_matches_by_synthetic_id(self, orchestrator):
        """Decisions with record_id matching _drift_event_id result in removal."""
        from src.agent.memory.eviction.eviction_rules import _drift_event_id

        d1 = make_drift(timestamp=100, subgoal_id="sg-1", signal_type="pattern_deviation")
        d2 = make_drift(timestamp=200, subgoal_id="sg-2", signal_type="stall")
        events = [d1, d2]

        # Sorted: d1 (idx 0), d2 (idx 1)
        sorted_events = sorted(events, key=lambda e: (e.timestamp, e.subgoal_id, e.signal_type))
        d1_id = _drift_event_id(0, sorted_events[0])

        decisions = [EvictionDecision(
            record_id=d1_id,
            record_type="drift_event",
            reason="DRIFT",
            evicted_at=NOW,
            details={},
        )]
        orchestrator._remove_drift_by_decisions(decisions, events)

        orchestrator._drift_memory.remove_events.assert_called_once_with([d1])

    def test_no_match_nothing_removed(self, orchestrator):
        """When no decision IDs match, remove_events is called with empty list."""
        d1 = make_drift(timestamp=100, subgoal_id="sg-1", signal_type="pattern_deviation")
        decisions = [make_decision("nonexistent", "drift_event")]

        orchestrator._remove_drift_by_decisions(decisions, [d1])

        orchestrator._drift_memory.remove_events.assert_called_once_with([])

    def test_empty_decisions_skips_remove(self, orchestrator):
        """When decisions list is empty, remove_events is not called."""
        orchestrator._remove_drift_by_decisions([], [make_drift()])

        orchestrator._drift_memory.remove_events.assert_not_called()

    def test_sort_consistency(self, orchestrator):
        """Events are sorted the same way as EvictionRules sorts them."""
        from src.agent.memory.eviction.eviction_rules import _drift_event_id

        # Insert out of timestamp order
        d_early = make_drift(timestamp=50, subgoal_id="sg-a", signal_type="a")
        d_late = make_drift(timestamp=100, subgoal_id="sg-b", signal_type="b")
        events = [d_late, d_early]  # reverse order

        # After sort: d_early (idx 0), d_late (idx 1)
        sorted_events = sorted(events, key=lambda e: (e.timestamp, e.subgoal_id, e.signal_type))
        early_id = _drift_event_id(0, sorted_events[0])

        decisions = [EvictionDecision(
            record_id=early_id,
            record_type="drift_event",
            reason="DRIFT",
            evicted_at=NOW,
            details={},
        )]
        orchestrator._remove_drift_by_decisions(decisions, events)

        # drift event 0 maps to the earliest event after sort = d_early
        orchestrator._drift_memory.remove_events.assert_called_once_with([d_early])
