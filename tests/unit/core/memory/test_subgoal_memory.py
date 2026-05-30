"""
Behaviour tests for 2.4.1 SubgoalMemory.

Design principles:
- Fakes over mocks: Subgoal is a pure dataclass, used directly.
- Behaviour focus: test what the memory does, not how it stores internally.
- Full round-trip fidelity (context, metadata, created_at, state).
"""
from __future__ import annotations

import pytest

from src.core.types.subgoal import Subgoal, SubgoalLifecycleState
from src.core.memory.subgoal_memory import SubgoalMemory
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord, SubgoalMemorySnapshot


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------

def make_subgoal(
    subgoal_id: str = "sg-001",
    goal: str = "do something",
    parent_id: str | None = None,
    state: SubgoalLifecycleState = SubgoalLifecycleState.CREATED,
    context: dict | None = None,
    metadata: dict | None = None,
    created_at: int = 1_000_000,
) -> Subgoal:
    return Subgoal(
        subgoal_id=subgoal_id,
        goal=goal,
        context=context or {},
        metadata=metadata or {"tag": "test"},
        parent_id=parent_id,
        state=state,
        created_at=created_at,
    )


@pytest.fixture
def memory() -> SubgoalMemory:
    return SubgoalMemory()


# ---------------------------------------------------------------------------
# put / get / exists
# ---------------------------------------------------------------------------

class TestPutGetExists:
    def test_get_returns_none_for_unknown(self, memory):
        assert memory.get("nonexistent") is None

    def test_exists_returns_false_for_unknown(self, memory):
        assert memory.exists("nonexistent") is False

    def test_put_then_exists(self, memory):
        sg = make_subgoal()
        memory.put(sg)
        assert memory.exists(sg.subgoal_id) is True

    def test_put_then_get_returns_equivalent_subgoal(self, memory):
        sg = make_subgoal(context={"key": "val"}, metadata={"m": 1})
        memory.put(sg)
        result = memory.get(sg.subgoal_id)
        assert result is not None
        assert result.subgoal_id == sg.subgoal_id
        assert result.goal == sg.goal
        assert result.context == sg.context
        assert result.metadata == sg.metadata
        assert result.parent_id == sg.parent_id
        assert result.state == sg.state
        assert result.created_at == sg.created_at

    def test_put_overwrites_existing(self, memory):
        sg1 = make_subgoal(state=SubgoalLifecycleState.CREATED)
        sg2 = make_subgoal(state=SubgoalLifecycleState.RUNNING)
        memory.put(sg1)
        memory.put(sg2)
        result = memory.get(sg1.subgoal_id)
        assert result.state == SubgoalLifecycleState.RUNNING

    def test_get_does_not_return_same_object_reference(self, memory):
        sg = make_subgoal(metadata={"x": 1})
        memory.put(sg)
        r1 = memory.get(sg.subgoal_id)
        r2 = memory.get(sg.subgoal_id)
        assert r1 is not r2

    def test_metadata_mutation_after_put_does_not_affect_store(self, memory):
        meta = {"key": "original"}
        sg = make_subgoal(metadata=meta)
        memory.put(sg)
        meta["key"] = "mutated"
        result = memory.get(sg.subgoal_id)
        assert result.metadata["key"] == "original"


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------

class TestListAll:
    def test_empty_store_returns_empty_list(self, memory):
        assert memory.list_all() == []

    def test_list_all_returns_all_stored(self, memory):
        sg1 = make_subgoal("sg-001", created_at=1000)
        sg2 = make_subgoal("sg-002", created_at=2000)
        memory.put(sg1)
        memory.put(sg2)
        ids = [s.subgoal_id for s in memory.list_all()]
        assert set(ids) == {"sg-001", "sg-002"}

    def test_list_all_sorted_by_created_at(self, memory):
        sg1 = make_subgoal("sg-001", created_at=3000)
        sg2 = make_subgoal("sg-002", created_at=1000)
        sg3 = make_subgoal("sg-003", created_at=2000)
        for sg in [sg1, sg2, sg3]:
            memory.put(sg)
        result = memory.list_all()
        assert [s.subgoal_id for s in result] == ["sg-002", "sg-003", "sg-001"]

    def test_list_all_deterministic(self, memory):
        for i in range(5):
            memory.put(make_subgoal(f"sg-{i:03}", created_at=i * 100))
        assert memory.list_all() == memory.list_all()


# ---------------------------------------------------------------------------
# Record serialisation
# ---------------------------------------------------------------------------

class TestRecordSerialisation:
    def test_record_state_stored_as_string(self, memory):
        sg = make_subgoal(state=SubgoalLifecycleState.RUNNING)
        memory.put(sg)
        record = memory._store[sg.subgoal_id]
        assert isinstance(record.state, str)
        assert record.state == "running"

    def test_record_fields_match_subgoal(self, memory):
        sg = make_subgoal(
            subgoal_id="sg-x",
            goal="test goal",
            parent_id="sg-parent",
            state=SubgoalLifecycleState.VALIDATED,
            context={"ctx": True},
            metadata={"m": 42},
            created_at=9999,
        )
        memory.put(sg)
        record = memory._store["sg-x"]
        assert record.subgoal_id == "sg-x"
        assert record.goal == "test goal"
        assert record.parent_id == "sg-parent"
        assert record.state == "validated"
        assert record.context == {"ctx": True}
        assert record.metadata == {"m": 42}
        assert record.created_at == 9999


# ---------------------------------------------------------------------------
# get_chain
# ---------------------------------------------------------------------------

class TestGetChain:
    def test_chain_for_unknown_id_is_empty(self, memory):
        assert memory.get_chain("nonexistent") == []

    def test_chain_for_root_is_single_record(self, memory):
        sg = make_subgoal("sg-root", parent_id=None)
        memory.put(sg)
        chain = memory.get_chain("sg-root")
        assert len(chain) == 1
        assert chain[0].subgoal_id == "sg-root"

    def test_chain_is_root_to_leaf(self, memory):
        root   = make_subgoal("root",  parent_id=None,    created_at=1000)
        middle = make_subgoal("mid",   parent_id="root",  created_at=2000)
        leaf   = make_subgoal("leaf",  parent_id="mid",   created_at=3000)
        for sg in [root, middle, leaf]:
            memory.put(sg)
        chain = memory.get_chain("leaf")
        assert [r.subgoal_id for r in chain] == ["root", "mid", "leaf"]

    def test_chain_stops_at_missing_parent(self, memory):
        child = make_subgoal("child", parent_id="missing-parent")
        memory.put(child)
        chain = memory.get_chain("child")
        assert [r.subgoal_id for r in chain] == ["child"]

    def test_chain_cycle_protection(self, memory):
        """Cycle: sg-a -> sg-b -> sg-a. Must not loop infinitely."""
        a = make_subgoal("sg-a", parent_id="sg-b")
        b = make_subgoal("sg-b", parent_id="sg-a")
        memory.put(a)
        memory.put(b)
        chain = memory.get_chain("sg-a")
        assert len(chain) <= 2  # cycle broken, not infinite


# ---------------------------------------------------------------------------
# get_children
# ---------------------------------------------------------------------------

class TestGetChildren:
    def test_no_children_returns_empty(self, memory):
        assert memory.get_children("sg-root") == []

    def test_children_returned_for_parent(self, memory):
        parent = make_subgoal("parent", parent_id=None)
        c1 = make_subgoal("child-1", parent_id="parent", created_at=1000)
        c2 = make_subgoal("child-2", parent_id="parent", created_at=2000)
        for sg in [parent, c1, c2]:
            memory.put(sg)
        children = memory.get_children("parent")
        assert {r.subgoal_id for r in children} == {"child-1", "child-2"}

    def test_children_sorted_by_created_at(self, memory):
        memory.put(make_subgoal("c-late",  parent_id="p", created_at=3000))
        memory.put(make_subgoal("c-early", parent_id="p", created_at=1000))
        memory.put(make_subgoal("c-mid",   parent_id="p", created_at=2000))
        result = memory.get_children("p")
        assert [r.subgoal_id for r in result] == ["c-early", "c-mid", "c-late"]

    def test_children_do_not_include_unrelated(self, memory):
        memory.put(make_subgoal("sg-a", parent_id="parent-1"))
        memory.put(make_subgoal("sg-b", parent_id="parent-2"))
        children = memory.get_children("parent-1")
        assert all(r.subgoal_id == "sg-a" for r in children)


# ---------------------------------------------------------------------------
# Snapshot round-trip
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_of_empty_store(self, memory):
        snap = memory.snapshot()
        assert snap.records == ()

    def test_snapshot_contains_all_records(self, memory):
        sg1 = make_subgoal("sg-001", created_at=1000)
        sg2 = make_subgoal("sg-002", created_at=2000)
        memory.put(sg1)
        memory.put(sg2)
        snap = memory.snapshot()
        ids = {r.subgoal_id for r in snap.records}
        assert ids == {"sg-001", "sg-002"}

    def test_snapshot_is_sorted_deterministically(self, memory):
        memory.put(make_subgoal("sg-z", created_at=3000))
        memory.put(make_subgoal("sg-a", created_at=1000))
        snap = memory.snapshot()
        assert snap.records[0].subgoal_id == "sg-a"
        assert snap.records[1].subgoal_id == "sg-z"

    def test_load_snapshot_restores_records(self, memory):
        sg1 = make_subgoal("sg-001", created_at=1000)
        sg2 = make_subgoal("sg-002", created_at=2000)
        memory.put(sg1)
        memory.put(sg2)
        snap = memory.snapshot()

        fresh = SubgoalMemory()
        fresh.load_snapshot(snap)

        assert fresh.exists("sg-001")
        assert fresh.exists("sg-002")

    def test_snapshot_round_trip_fidelity(self, memory):
        sg = make_subgoal("sg-001", context={"k": "v"}, metadata={"m": 1}, created_at=5000)
        memory.put(sg)
        snap = memory.snapshot()

        fresh = SubgoalMemory()
        fresh.load_snapshot(snap)
        result = fresh.get("sg-001")

        assert result.subgoal_id == sg.subgoal_id
        assert result.goal == sg.goal
        assert result.context == sg.context
        assert result.metadata == sg.metadata
        assert result.state == sg.state
        assert result.created_at == sg.created_at

    def test_load_snapshot_replaces_existing_store(self, memory):
        memory.put(make_subgoal("old-sg"))
        empty_snap = SubgoalMemorySnapshot(records=())
        memory.load_snapshot(empty_snap)
        assert not memory.exists("old-sg")
        assert memory.list_all() == []

    def test_snapshot_is_immutable_type(self, memory):
        memory.put(make_subgoal("sg-001"))
        snap = memory.snapshot()
        assert isinstance(snap, SubgoalMemorySnapshot)
        assert isinstance(snap.records, tuple)
