from __future__ import annotations

import pytest

from src.core.memory.drift_memory import DriftMemory
from src.core.memory.drift_memory_types import DriftEvent, DriftMemorySnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_event(
    timestamp: int = 1000,
    subgoal_id: str = "sg-1",
    segment_id: str | None = "seg-1",
    step_id: str | None = "step-1",
    signal_type: str = "planning_deviation",
    confidence: float = 0.5,
    details: dict | None = None,
) -> DriftEvent:
    return DriftEvent(
        timestamp=timestamp,
        subgoal_id=subgoal_id,
        segment_id=segment_id,
        step_id=step_id,
        signal_type=signal_type,
        confidence=confidence,
        details=details or {},
    )


# ---------------------------------------------------------------------------
# DriftEvent construction and validation
# ---------------------------------------------------------------------------

class TestDriftEvent:
    def test_valid_event_constructs(self):
        e = make_event()
        assert e.subgoal_id == "sg-1"
        assert e.confidence == 0.5

    def test_negative_timestamp_raises(self):
        with pytest.raises(ValueError, match="timestamp"):
            make_event(timestamp=-1)

    def test_confidence_above_one_raises(self):
        with pytest.raises(ValueError, match="confidence"):
            make_event(confidence=1.1)

    def test_confidence_below_zero_raises(self):
        with pytest.raises(ValueError, match="confidence"):
            make_event(confidence=-0.1)

    def test_confidence_boundary_values_accepted(self):
        make_event(confidence=0.0)
        make_event(confidence=1.0)

    def test_empty_subgoal_id_raises(self):
        with pytest.raises(ValueError, match="subgoal_id"):
            make_event(subgoal_id="")

    def test_details_deep_copied_on_construction(self):
        original = {"key": "value"}
        e = make_event(details=original)
        original["key"] = "mutated"
        assert e.details["key"] == "value"

    def test_event_is_frozen(self):
        e = make_event()
        with pytest.raises((AttributeError, TypeError)):
            e.confidence = 0.9  # type: ignore

    def test_optional_fields_can_be_none(self):
        e = make_event(segment_id=None, step_id=None)
        assert e.segment_id is None
        assert e.step_id is None


# ---------------------------------------------------------------------------
# Ring-buffer capacity behaviour
# ---------------------------------------------------------------------------

class TestRingBuffer:
    def test_capacity_zero_raises(self):
        with pytest.raises(ValueError, match="capacity"):
            DriftMemory(capacity=0)

    def test_negative_capacity_raises(self):
        with pytest.raises(ValueError, match="capacity"):
            DriftMemory(capacity=-1)

    def test_events_within_capacity_all_retained(self):
        mem = DriftMemory(capacity=5)
        for i in range(5):
            mem.record(make_event(timestamp=i * 1000))
        assert len(mem) == 5

    def test_oldest_dropped_when_capacity_exceeded(self):
        mem = DriftMemory(capacity=3)
        events = [make_event(timestamp=i * 1000, subgoal_id=f"sg-{i}") for i in range(5)]
        for e in events:
            mem.record(e)
        assert len(mem) == 3
        retained = mem.recent(3)
        # oldest two (sg-0, sg-1) should be gone
        subgoal_ids = [e.subgoal_id for e in retained]
        assert "sg-0" not in subgoal_ids
        assert "sg-1" not in subgoal_ids
        assert "sg-4" in subgoal_ids

    def test_default_capacity_is_20(self):
        mem = DriftMemory()
        assert mem.capacity == 20

    def test_ordering_is_oldest_first(self):
        mem = DriftMemory(capacity=5)
        for i in range(3):
            mem.record(make_event(timestamp=i * 1000))
        events = mem.recent(3)
        timestamps = [e.timestamp for e in events]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# record / recent / last
# ---------------------------------------------------------------------------

class TestRecordRecentLast:
    def test_record_and_recent_all(self):
        mem = DriftMemory()
        e1 = make_event(timestamp=1000)
        e2 = make_event(timestamp=2000)
        mem.record(e1)
        mem.record(e2)
        assert mem.recent(2) == [e1, e2]

    def test_recent_n_returns_most_recent(self):
        mem = DriftMemory()
        events = [make_event(timestamp=i * 1000) for i in range(5)]
        for e in events:
            mem.record(e)
        result = mem.recent(2)
        assert len(result) == 2
        assert result == events[-2:]

    def test_recent_zero_returns_empty(self):
        mem = DriftMemory()
        mem.record(make_event())
        assert mem.recent(0) == []

    def test_recent_negative_returns_empty(self):
        mem = DriftMemory()
        mem.record(make_event())
        assert mem.recent(-5) == []

    def test_recent_n_larger_than_buffer_returns_all(self):
        mem = DriftMemory()
        mem.record(make_event(timestamp=1000))
        mem.record(make_event(timestamp=2000))
        assert len(mem.recent(100)) == 2

    def test_last_returns_most_recent_event(self):
        mem = DriftMemory()
        e1 = make_event(timestamp=1000)
        e2 = make_event(timestamp=2000)
        mem.record(e1)
        mem.record(e2)
        assert mem.last() == e2

    def test_last_returns_none_when_empty(self):
        mem = DriftMemory()
        assert mem.last() is None

    def test_clear_empties_buffer(self):
        mem = DriftMemory()
        mem.record(make_event())
        mem.clear()
        assert len(mem) == 0
        assert mem.last() is None
        assert mem.recent(10) == []


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

class TestFiltering:
    def test_filter_by_subgoal_returns_matching(self):
        mem = DriftMemory()
        mem.record(make_event(subgoal_id="sg-a", timestamp=1000))
        mem.record(make_event(subgoal_id="sg-b", timestamp=2000))
        mem.record(make_event(subgoal_id="sg-a", timestamp=3000))
        results = mem.filter_by_subgoal("sg-a")
        assert len(results) == 2
        assert all(e.subgoal_id == "sg-a" for e in results)

    def test_filter_by_subgoal_empty_when_no_match(self):
        mem = DriftMemory()
        mem.record(make_event(subgoal_id="sg-x"))
        assert mem.filter_by_subgoal("ghost") == []

    def test_filter_by_signal_returns_matching(self):
        mem = DriftMemory()
        mem.record(make_event(signal_type="planning_deviation", timestamp=1000))
        mem.record(make_event(signal_type="loop_anomaly", timestamp=2000))
        mem.record(make_event(signal_type="planning_deviation", timestamp=3000))
        results = mem.filter_by_signal("planning_deviation")
        assert len(results) == 2
        assert all(e.signal_type == "planning_deviation" for e in results)

    def test_filter_by_signal_empty_when_no_match(self):
        mem = DriftMemory()
        mem.record(make_event(signal_type="planning_deviation"))
        assert mem.filter_by_signal("ghost") == []

    def test_filter_preserves_oldest_first_order(self):
        mem = DriftMemory()
        mem.record(make_event(subgoal_id="sg-a", timestamp=1000))
        mem.record(make_event(subgoal_id="sg-a", timestamp=3000))
        results = mem.filter_by_subgoal("sg-a")
        assert results[0].timestamp < results[1].timestamp

    def test_count_recent_counts_within_window(self):
        mem = DriftMemory()
        for _ in range(3):
            mem.record(make_event(signal_type="planning_deviation"))
        for _ in range(2):
            mem.record(make_event(signal_type="loop_anomaly"))
        # window=3 covers the last 3 events: 1 planning_deviation + 2 loop_anomaly
        assert mem.count_recent("planning_deviation", window=3) == 1
        assert mem.count_recent("loop_anomaly", window=3) == 2

    def test_count_recent_window_zero_returns_zero(self):
        mem = DriftMemory()
        mem.record(make_event(signal_type="planning_deviation"))
        assert mem.count_recent("planning_deviation", window=0) == 0

    def test_count_recent_negative_window_returns_zero(self):
        mem = DriftMemory()
        mem.record(make_event(signal_type="planning_deviation"))
        assert mem.count_recent("planning_deviation", window=-1) == 0

    def test_count_recent_window_larger_than_buffer(self):
        mem = DriftMemory()
        mem.record(make_event(signal_type="planning_deviation"))
        mem.record(make_event(signal_type="planning_deviation"))
        assert mem.count_recent("planning_deviation", window=100) == 2


# ---------------------------------------------------------------------------
# Snapshot round-trip
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_contains_all_events(self):
        mem = DriftMemory()
        e1 = make_event(timestamp=1000)
        e2 = make_event(timestamp=2000)
        mem.record(e1)
        mem.record(e2)
        snap = mem.snapshot()
        assert len(snap.events) == 2
        assert e1 in snap.events
        assert e2 in snap.events

    def test_load_snapshot_restores_events(self):
        mem = DriftMemory()
        e = make_event(timestamp=5000, subgoal_id="sg-restore")
        mem.record(e)
        snap = mem.snapshot()

        mem2 = DriftMemory()
        mem2.load_snapshot(snap)
        assert mem2.last() == e
        assert len(mem2) == 1

    def test_load_snapshot_replaces_existing_buffer(self):
        mem = DriftMemory()
        mem.record(make_event(timestamp=1000))
        snap = mem.snapshot()

        mem.record(make_event(timestamp=2000))
        assert len(mem) == 2

        mem.load_snapshot(snap)
        assert len(mem) == 1

    def test_load_snapshot_respects_capacity(self):
        """Oversize snapshot: only most recent capacity events are loaded."""
        full_mem = DriftMemory(capacity=10)
        for i in range(10):
            full_mem.record(make_event(timestamp=i * 1000))
        snap = full_mem.snapshot()

        small_mem = DriftMemory(capacity=3)
        small_mem.load_snapshot(snap)
        assert len(small_mem) == 3
        # most recent 3 events (timestamps 7000, 8000, 9000) should be retained
        timestamps = [e.timestamp for e in small_mem.recent(3)]
        assert 9000 in timestamps
        assert 0 not in timestamps

    def test_snapshot_is_frozen(self):
        snap = DriftMemorySnapshot(events=())
        with pytest.raises((AttributeError, TypeError)):
            snap.events = ()  # type: ignore

    def test_snapshot_ordering_is_oldest_first(self):
        mem = DriftMemory()
        for i in range(3):
            mem.record(make_event(timestamp=i * 1000))
        snap = mem.snapshot()
        timestamps = [e.timestamp for e in snap.events]
        assert timestamps == sorted(timestamps)

    def test_empty_snapshot_round_trip(self):
        mem = DriftMemory()
        snap = mem.snapshot()
        mem2 = DriftMemory()
        mem2.load_snapshot(snap)
        assert len(mem2) == 0


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------

class TestDeterministicOrdering:
    def test_recent_stable_across_calls(self):
        mem = DriftMemory()
        for i in range(5):
            mem.record(make_event(timestamp=i * 1000))
        assert mem.recent(5) == mem.recent(5)

    def test_filter_stable_across_calls(self):
        mem = DriftMemory()
        for i in range(4):
            mem.record(make_event(subgoal_id="sg-a", timestamp=i * 1000))
        assert mem.filter_by_subgoal("sg-a") == mem.filter_by_subgoal("sg-a")

    def test_ring_buffer_eviction_is_deterministic(self):
        mem = DriftMemory(capacity=3)
        events = [make_event(timestamp=i * 1000, subgoal_id=f"sg-{i}") for i in range(6)]
        for e in events:
            mem.record(e)
        result = mem.recent(3)
        assert [e.subgoal_id for e in result] == ["sg-3", "sg-4", "sg-5"]
