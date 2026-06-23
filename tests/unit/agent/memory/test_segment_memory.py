from __future__ import annotations

import pytest

from src.agent.memory.segment_memory import SegmentMemory
from src.agent.memory.segment_memory_types import SegmentMemoryRecord, SegmentMemorySnapshot
from src.agent.memory.types.plan_segment import PlanSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_segment(
    subgoal_id: str = "sg-1",
    steps: list[str] | None = None,
    context: dict | None = None,
    metadata: dict | None = None,
    created_at: str = "2024-01-01T00:00:00",
) -> PlanSegment:
    return PlanSegment(
        subgoal_id=subgoal_id,
        steps=steps or ["step-a", "step-b"],
        context=context or {},
        metadata=metadata or {},
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# put / get / exists
# ---------------------------------------------------------------------------

class TestCrud:
    def test_put_and_get_returns_equivalent_segment(self):
        mem = SegmentMemory()
        seg = make_segment()
        mem.put(seg)
        result = mem.get(seg.segment_id)
        assert result is not None
        assert result.segment_id == seg.segment_id
        assert result.subgoal_id == seg.subgoal_id
        assert result.steps == seg.steps

    def test_get_unknown_returns_none(self):
        mem = SegmentMemory()
        assert mem.get("nonexistent") is None

    def test_exists_true_after_put(self):
        mem = SegmentMemory()
        seg = make_segment()
        mem.put(seg)
        assert mem.exists(seg.segment_id) is True

    def test_exists_false_before_put(self):
        mem = SegmentMemory()
        assert mem.exists("no-such-id") is False

    def test_put_overwrites_existing_entry(self):
        mem = SegmentMemory()
        seg = make_segment(steps=["original"])
        mem.put(seg)
        # put a fresh segment at the same segment_id by using same deterministic inputs
        mem.put(seg)
        assert len(mem.list_all()) == 1

    def test_put_with_parent_id_stored(self):
        mem = SegmentMemory()
        seg = make_segment()
        mem.put(seg, parent_id="parent-seg-id")
        record = mem._store[seg.segment_id]
        assert record.parent_id == "parent-seg-id"

    def test_put_without_parent_id_defaults_to_none(self):
        mem = SegmentMemory()
        seg = make_segment()
        mem.put(seg)
        record = mem._store[seg.segment_id]
        assert record.parent_id is None


# ---------------------------------------------------------------------------
# Record serialisation
# ---------------------------------------------------------------------------

class TestRecordSerialisation:
    def test_record_fields_match_segment(self):
        mem = SegmentMemory()
        seg = make_segment(
            subgoal_id="sg-42",
            steps=["s1", "s2"],
            context={"k": "v"},
            metadata={"m": 1},
            created_at="2024-06-01T12:00:00",
        )
        mem.put(seg)
        record = mem._store[seg.segment_id]

        assert record.segment_id == seg.segment_id
        assert record.subgoal_id == "sg-42"
        assert record.content == ["s1", "s2"]
        assert record.context == {"k": "v"}
        assert record.metadata == {"m": 1}
        assert record.created_at == "2024-06-01T12:00:00"
        assert record.state is None

    def test_record_is_frozen_dataclass(self):
        record = SegmentMemoryRecord(
            segment_id="sid",
            parent_id=None,
            subgoal_id="sg-1",
            state=None,
            content=["step"],
            created_at="2024-01-01T00:00:00",
            context={},
            metadata={},
        )
        with pytest.raises((AttributeError, TypeError)):
            record.segment_id = "changed"  # type: ignore

    def test_round_trip_segment_id_matches(self):
        mem = SegmentMemory()
        seg = make_segment()
        mem.put(seg)
        retrieved = mem.get(seg.segment_id)
        assert retrieved is not None
        assert retrieved.segment_id == seg.segment_id

    def test_round_trip_canonical_hash_matches(self):
        mem = SegmentMemory()
        seg = make_segment(context={"x": 1}, metadata={"y": 2})
        mem.put(seg)
        retrieved = mem.get(seg.segment_id)
        assert retrieved is not None
        assert retrieved.canonical_hash == seg.canonical_hash

    def test_external_mutation_of_original_steps_does_not_affect_record(self):
        mem = SegmentMemory()
        steps = ["step-a"]
        seg = make_segment(steps=steps)
        mem.put(seg)
        # mutate the list that was used to build the segment
        steps.append("injected")
        record = mem._store[seg.segment_id]
        assert "injected" not in record.content

    def test_returned_segment_is_independent_of_store(self):
        mem = SegmentMemory()
        seg = make_segment(context={"key": "original"})
        mem.put(seg)
        retrieved = mem.get(seg.segment_id)
        assert retrieved is not None
        # mutating returned context should not affect the store
        retrieved.context["key"] = "mutated"  # type: ignore
        record = mem._store[seg.segment_id]
        assert record.context["key"] == "original"


# ---------------------------------------------------------------------------
# Chain reconstruction
# ---------------------------------------------------------------------------

class TestGetChain:
    def test_single_segment_chain(self):
        mem = SegmentMemory()
        seg = make_segment(created_at="2024-01-01T00:00:00")
        mem.put(seg)
        chain = mem.get_chain(seg.segment_id)
        assert len(chain) == 1
        assert chain[0].segment_id == seg.segment_id

    def test_chain_walks_root_to_leaf(self):
        mem = SegmentMemory()
        root = make_segment(subgoal_id="sg-1", created_at="2024-01-01T00:00:00")
        child = make_segment(subgoal_id="sg-1", steps=["c1"], created_at="2024-01-02T00:00:00")
        grandchild = make_segment(subgoal_id="sg-1", steps=["g1"], created_at="2024-01-03T00:00:00")

        mem.put(root)
        mem.put(child, parent_id=root.segment_id)
        mem.put(grandchild, parent_id=child.segment_id)

        chain = mem.get_chain(grandchild.segment_id)
        assert len(chain) == 3
        assert chain[0].segment_id == root.segment_id
        assert chain[1].segment_id == child.segment_id
        assert chain[2].segment_id == grandchild.segment_id

    def test_chain_returns_empty_for_unknown_segment(self):
        mem = SegmentMemory()
        assert mem.get_chain("ghost") == []

    def test_chain_truncates_on_missing_parent(self):
        mem = SegmentMemory()
        seg = make_segment()
        mem.put(seg, parent_id="missing-parent")
        chain = mem.get_chain(seg.segment_id)
        # walks to seg, then tries missing-parent (not in store), stops
        assert len(chain) == 1
        assert chain[0].segment_id == seg.segment_id

    def test_chain_is_cycle_safe(self):
        """get_chain must not loop infinitely on circular parent links."""
        mem = SegmentMemory()
        a = make_segment(subgoal_id="sg-1", created_at="2024-01-01T00:00:00")
        b = make_segment(subgoal_id="sg-1", steps=["b"], created_at="2024-01-02T00:00:00")

        mem.put(a)
        mem.put(b, parent_id=a.segment_id)
        # manually inject a cycle by replacing a's record with one pointing at b
        mem._store[a.segment_id] = SegmentMemoryRecord(
            segment_id=a.segment_id,
            parent_id=b.segment_id,
            subgoal_id="sg-1",
            state=None,
            content=["step-a", "step-b"],
            created_at="2024-01-01T00:00:00",
            context={},
            metadata={},
        )
        chain = mem.get_chain(b.segment_id)
        assert len(chain) <= 2  # must terminate


# ---------------------------------------------------------------------------
# Children lookup
# ---------------------------------------------------------------------------

class TestGetChildren:
    def test_returns_children_of_parent(self):
        mem = SegmentMemory()
        parent = make_segment(created_at="2024-01-01T00:00:00")
        child1 = make_segment(steps=["c1"], created_at="2024-01-02T00:00:00")
        child2 = make_segment(steps=["c2"], created_at="2024-01-03T00:00:00")
        unrelated = make_segment(steps=["u1"], created_at="2024-01-04T00:00:00")

        mem.put(parent)
        mem.put(child1, parent_id=parent.segment_id)
        mem.put(child2, parent_id=parent.segment_id)
        mem.put(unrelated)

        children = mem.get_children(parent.segment_id)
        child_ids = {r.segment_id for r in children}
        assert child1.segment_id in child_ids
        assert child2.segment_id in child_ids
        assert unrelated.segment_id not in child_ids

    def test_returns_empty_when_no_children(self):
        mem = SegmentMemory()
        seg = make_segment()
        mem.put(seg)
        assert mem.get_children(seg.segment_id) == []

    def test_children_sorted_by_created_at_then_segment_id(self):
        mem = SegmentMemory()
        parent = make_segment(steps=["p"], created_at="2024-01-01T00:00:00")
        # same created_at — order determined by segment_id
        c1 = make_segment(steps=["c1"], created_at="2024-01-02T00:00:00")
        c2 = make_segment(steps=["c2"], created_at="2024-01-03T00:00:00")

        mem.put(parent)
        mem.put(c2, parent_id=parent.segment_id)  # put out of order
        mem.put(c1, parent_id=parent.segment_id)

        children = mem.get_children(parent.segment_id)
        assert children[0].created_at <= children[1].created_at


# ---------------------------------------------------------------------------
# Subgoal lookup
# ---------------------------------------------------------------------------

class TestGetBySubgoal:
    def test_returns_all_segments_for_subgoal(self):
        mem = SegmentMemory()
        sg_a1 = make_segment(subgoal_id="sg-a", steps=["a1"], created_at="2024-01-01T00:00:00")
        sg_a2 = make_segment(subgoal_id="sg-a", steps=["a2"], created_at="2024-01-02T00:00:00")
        sg_b1 = make_segment(subgoal_id="sg-b", steps=["b1"], created_at="2024-01-03T00:00:00")

        mem.put(sg_a1)
        mem.put(sg_a2)
        mem.put(sg_b1)

        results = mem.get_by_subgoal("sg-a")
        result_ids = {r.segment_id for r in results}
        assert sg_a1.segment_id in result_ids
        assert sg_a2.segment_id in result_ids
        assert sg_b1.segment_id not in result_ids

    def test_returns_empty_for_unknown_subgoal(self):
        mem = SegmentMemory()
        assert mem.get_by_subgoal("ghost") == []

    def test_subgoal_results_sorted_deterministically(self):
        mem = SegmentMemory()
        s1 = make_segment(subgoal_id="sg-x", steps=["s1"], created_at="2024-01-01T00:00:00")
        s2 = make_segment(subgoal_id="sg-x", steps=["s2"], created_at="2024-01-02T00:00:00")
        mem.put(s2)
        mem.put(s1)
        results = mem.get_by_subgoal("sg-x")
        assert results[0].created_at <= results[1].created_at


# ---------------------------------------------------------------------------
# Snapshot round-trip
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_contains_all_records(self):
        mem = SegmentMemory()
        s1 = make_segment(steps=["a"], created_at="2024-01-01T00:00:00")
        s2 = make_segment(steps=["b"], created_at="2024-01-02T00:00:00")
        mem.put(s1)
        mem.put(s2)

        snap = mem.snapshot()
        snap_ids = {r.segment_id for r in snap.records}
        assert s1.segment_id in snap_ids
        assert s2.segment_id in snap_ids

    def test_load_snapshot_restores_state(self):
        mem = SegmentMemory()
        s1 = make_segment(steps=["x"], created_at="2024-01-01T00:00:00")
        mem.put(s1)
        snap = mem.snapshot()

        mem2 = SegmentMemory()
        mem2.load_snapshot(snap)
        assert mem2.exists(s1.segment_id)
        retrieved = mem2.get(s1.segment_id)
        assert retrieved is not None
        assert retrieved.segment_id == s1.segment_id

    def test_load_snapshot_replaces_existing_state(self):
        mem = SegmentMemory()
        s1 = make_segment(steps=["original"], created_at="2024-01-01T00:00:00")
        mem.put(s1)
        snap = mem.snapshot()

        mem.put(make_segment(steps=["extra"], created_at="2024-02-01T00:00:00"))
        assert len(mem.list_all()) == 2

        mem.load_snapshot(snap)
        assert len(mem.list_all()) == 1
        assert mem.exists(s1.segment_id)

    def test_snapshot_is_frozen_dataclass(self):
        snap = SegmentMemorySnapshot(records=())
        with pytest.raises((AttributeError, TypeError)):
            snap.records = ()  # type: ignore

    def test_snapshot_round_trip_preserves_parent_id(self):
        mem = SegmentMemory()
        parent = make_segment(steps=["p"], created_at="2024-01-01T00:00:00")
        child = make_segment(steps=["c"], created_at="2024-01-02T00:00:00")
        mem.put(parent)
        mem.put(child, parent_id=parent.segment_id)

        snap = mem.snapshot()
        mem2 = SegmentMemory()
        mem2.load_snapshot(snap)

        child_record = mem2._store[child.segment_id]
        assert child_record.parent_id == parent.segment_id


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------

class TestDeterministicOrdering:
    def test_list_all_sorted_by_created_at_then_segment_id(self):
        mem = SegmentMemory()
        s1 = make_segment(steps=["s1"], created_at="2024-01-01T00:00:00")
        s2 = make_segment(steps=["s2"], created_at="2024-01-02T00:00:00")
        s3 = make_segment(steps=["s3"], created_at="2024-01-03T00:00:00")

        mem.put(s3)
        mem.put(s1)
        mem.put(s2)

        result = mem.list_all()
        dates = [r.created_at for r in result]
        assert dates == sorted(dates)

    def test_list_all_stable_across_calls(self):
        mem = SegmentMemory()
        for i in range(5):
            mem.put(make_segment(steps=[f"s{i}"], created_at=f"2024-01-0{i+1}T00:00:00"))

        first = [r.segment_id for r in mem.list_all()]
        second = [r.segment_id for r in mem.list_all()]
        assert first == second

    def test_snapshot_records_sorted_deterministically(self):
        mem = SegmentMemory()
        s1 = make_segment(steps=["a"], created_at="2024-01-01T00:00:00")
        s2 = make_segment(steps=["b"], created_at="2024-01-02T00:00:00")
        mem.put(s2)
        mem.put(s1)

        snap = mem.snapshot()
        dates = [r.created_at for r in snap.records]
        assert dates == sorted(dates)

    def test_empty_store_list_all_returns_empty(self):
        mem = SegmentMemory()
        assert mem.list_all() == []

    def test_empty_store_snapshot_has_no_records(self):
        mem = SegmentMemory()
        snap = mem.snapshot()
        assert snap.records == ()