from __future__ import annotations

import pytest

from src.strategy.memory.plan_memory import PlanMemory
from src.strategy.memory.plan_memory_types import PlanMemoryRecord, PlanMemorySnapshot
from src.strategy.planning.models.plan import Plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_plan(
    intent: str = "test-intent",
    targetskillid: str = "skill-1",
    arguments: dict | None = None,
    reasoning_summary: str = "test reasoning",
) -> Plan:
    return Plan(
        intent=intent,
        targetskillid=targetskillid,
        arguments=arguments if arguments is not None else {"key": "value"},
        reasoning_summary=reasoning_summary,
    )


def put_plan(
    mem: PlanMemory,
    plan: Plan,
    plan_id: str = "plan-1",
    subgoal_id: str = "sg-1",
    segments: list[str] | None = None,
    created_at: str = "2024-01-01T00:00:00",
    metadata: dict | None = None,
) -> None:
    mem.put(
        plan=plan,
        plan_id=plan_id,
        subgoal_id=subgoal_id,
        segments=segments or ["seg-a", "seg-b"],
        created_at=created_at,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# put / get / exists
# ---------------------------------------------------------------------------

class TestCrud:
    def test_put_and_get_returns_equivalent_plan(self):
        mem = PlanMemory()
        plan = make_plan()
        put_plan(mem, plan, plan_id="p1")
        result = mem.get("p1")
        assert result is not None
        assert result.intent == plan.intent
        assert result.targetskillid == plan.targetskillid
        assert result.arguments == plan.arguments
        assert result.reasoning_summary == plan.reasoning_summary

    def test_get_unknown_returns_none(self):
        mem = PlanMemory()
        assert mem.get("nonexistent") is None

    def test_exists_true_after_put(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(), plan_id="p1")
        assert mem.exists("p1") is True

    def test_exists_false_before_put(self):
        mem = PlanMemory()
        assert mem.exists("ghost") is False

    def test_put_overwrites_existing_entry(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(intent="first"), plan_id="p1")
        put_plan(mem, make_plan(intent="second"), plan_id="p1")
        result = mem.get("p1")
        assert result is not None
        assert result.intent == "second"
        assert len(mem.list_all()) == 1

    def test_get_record_returns_full_identity(self):
        mem = PlanMemory()
        plan = make_plan()
        put_plan(mem, plan, plan_id="p1", subgoal_id="sg-42", segments=["s1", "s2"])
        record = mem.get_record("p1")
        assert record is not None
        assert record.plan_id == "p1"
        assert record.subgoal_id == "sg-42"
        assert record.segments == ["s1", "s2"]

    def test_get_record_unknown_returns_none(self):
        mem = PlanMemory()
        assert mem.get_record("ghost") is None

    def test_metadata_defaults_to_empty_dict(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(), plan_id="p1", metadata=None)
        record = mem.get_record("p1")
        assert record is not None
        assert record.metadata == {}


# ---------------------------------------------------------------------------
# Record serialisation
# ---------------------------------------------------------------------------

class TestRecordSerialisation:
    def test_record_fields_match_inputs(self):
        mem = PlanMemory()
        plan = make_plan(intent="buy-milk", targetskillid="sk-99", arguments={"qty": 2})
        mem.put(
            plan=plan,
            plan_id="plan-xyz",
            subgoal_id="sg-abc",
            segments=["seg-1"],
            created_at="2024-06-01T12:00:00",
            metadata={"tag": "v1"},
        )
        record = mem.get_record("plan-xyz")
        assert record is not None
        assert record.plan_id == "plan-xyz"
        assert record.subgoal_id == "sg-abc"
        assert record.segments == ["seg-1"]
        assert record.created_at == "2024-06-01T12:00:00"
        assert record.metadata == {"tag": "v1"}
        assert record.intent == "buy-milk"
        assert record.targetskillid == "sk-99"
        assert record.arguments == {"qty": 2}

    def test_record_is_frozen_dataclass(self):
        record = PlanMemoryRecord(
            plan_id="p",
            subgoal_id="sg",
            segments=[],
            created_at="2024-01-01T00:00:00",
            metadata={},
            intent="i",
            targetskillid="sk",
            arguments={},
            reasoning_summary="r",
        )
        with pytest.raises((AttributeError, TypeError)):
            record.plan_id = "changed"  # type: ignore

    def test_round_trip_plan_fields_preserved(self):
        mem = PlanMemory()
        plan = make_plan(intent="deploy", arguments={"env": "prod"})
        put_plan(mem, plan, plan_id="p1")
        retrieved = mem.get("p1")
        assert retrieved is not None
        assert retrieved.intent == "deploy"
        assert retrieved.arguments == {"env": "prod"}

    def test_external_mutation_of_arguments_does_not_affect_record(self):
        mem = PlanMemory()
        args = {"x": 1}
        plan = make_plan(arguments=args)
        put_plan(mem, plan, plan_id="p1")
        args["x"] = 99
        record = mem.get_record("p1")
        assert record is not None
        assert record.arguments["x"] == 1

    def test_returned_plan_arguments_are_independent_of_store(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(arguments={"key": "original"}), plan_id="p1")
        retrieved = mem.get("p1")
        assert retrieved is not None
        retrieved.arguments["key"] = "mutated"
        record = mem.get_record("p1")
        assert record is not None
        assert record.arguments["key"] == "original"

    def test_segments_list_is_independent_of_caller(self):
        mem = PlanMemory()
        segs = ["s1", "s2"]
        put_plan(mem, make_plan(), plan_id="p1", segments=segs)
        segs.append("s3")
        assert mem.get_segments("p1") == ["s1", "s2"]


# ---------------------------------------------------------------------------
# Subgoal lookup
# ---------------------------------------------------------------------------

class TestGetBySubgoal:
    def test_returns_all_plans_for_subgoal(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(intent="a"), plan_id="p1", subgoal_id="sg-a", created_at="2024-01-01T00:00:00")
        put_plan(mem, make_plan(intent="b"), plan_id="p2", subgoal_id="sg-a", created_at="2024-01-02T00:00:00")
        put_plan(mem, make_plan(intent="c"), plan_id="p3", subgoal_id="sg-b", created_at="2024-01-03T00:00:00")

        results = mem.get_by_subgoal("sg-a")
        plan_ids = {r.plan_id for r in results}
        assert "p1" in plan_ids
        assert "p2" in plan_ids
        assert "p3" not in plan_ids

    def test_returns_empty_for_unknown_subgoal(self):
        mem = PlanMemory()
        assert mem.get_by_subgoal("ghost") == []

    def test_results_sorted_by_created_at_then_plan_id(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(), plan_id="p2", subgoal_id="sg-x", created_at="2024-01-02T00:00:00")
        put_plan(mem, make_plan(), plan_id="p1", subgoal_id="sg-x", created_at="2024-01-01T00:00:00")

        results = mem.get_by_subgoal("sg-x")
        assert results[0].plan_id == "p1"
        assert results[1].plan_id == "p2"


# ---------------------------------------------------------------------------
# Segment lookup
# ---------------------------------------------------------------------------

class TestGetSegments:
    def test_returns_segment_ids_for_plan(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(), plan_id="p1", segments=["seg-1", "seg-2", "seg-3"])
        assert mem.get_segments("p1") == ["seg-1", "seg-2", "seg-3"]

    def test_returns_empty_for_unknown_plan(self):
        mem = PlanMemory()
        assert mem.get_segments("ghost") == []

    def test_returned_list_is_independent_of_store(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(), plan_id="p1", segments=["s1"])
        segs = mem.get_segments("p1")
        segs.append("injected")
        assert mem.get_segments("p1") == ["s1"]


# ---------------------------------------------------------------------------
# Latest plan retrieval
# ---------------------------------------------------------------------------

class TestGetLatestForSubgoal:
    def test_returns_most_recent_plan(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(intent="old"), plan_id="p1", subgoal_id="sg-1", created_at="2024-01-01T00:00:00")
        put_plan(mem, make_plan(intent="new"), plan_id="p2", subgoal_id="sg-1", created_at="2024-01-02T00:00:00")

        latest = mem.get_latest_for_subgoal("sg-1")
        assert latest is not None
        assert latest.plan_id == "p2"

    def test_returns_none_for_unknown_subgoal(self):
        mem = PlanMemory()
        assert mem.get_latest_for_subgoal("ghost") is None

    def test_single_plan_is_latest(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(), plan_id="p1", subgoal_id="sg-1", created_at="2024-01-01T00:00:00")
        latest = mem.get_latest_for_subgoal("sg-1")
        assert latest is not None
        assert latest.plan_id == "p1"

    def test_deterministic_when_same_created_at(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(), plan_id="p-aaa", subgoal_id="sg-1", created_at="2024-01-01T00:00:00")
        put_plan(mem, make_plan(), plan_id="p-zzz", subgoal_id="sg-1", created_at="2024-01-01T00:00:00")

        # sorted by (created_at, plan_id) — "p-zzz" is last
        latest = mem.get_latest_for_subgoal("sg-1")
        assert latest is not None
        assert latest.plan_id == "p-zzz"


# ---------------------------------------------------------------------------
# Snapshot round-trip
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_contains_all_records(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(), plan_id="p1", created_at="2024-01-01T00:00:00")
        put_plan(mem, make_plan(), plan_id="p2", created_at="2024-01-02T00:00:00")

        snap = mem.snapshot()
        snap_ids = {r.plan_id for r in snap.records}
        assert "p1" in snap_ids
        assert "p2" in snap_ids

    def test_load_snapshot_restores_state(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(intent="original"), plan_id="p1", created_at="2024-01-01T00:00:00")
        snap = mem.snapshot()

        mem2 = PlanMemory()
        mem2.load_snapshot(snap)
        assert mem2.exists("p1")
        result = mem2.get("p1")
        assert result is not None
        assert result.intent == "original"

    def test_load_snapshot_replaces_existing_state(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(), plan_id="p1", created_at="2024-01-01T00:00:00")
        snap = mem.snapshot()

        put_plan(mem, make_plan(), plan_id="p2", created_at="2024-02-01T00:00:00")
        assert len(mem.list_all()) == 2

        mem.load_snapshot(snap)
        assert len(mem.list_all()) == 1
        assert mem.exists("p1")
        assert not mem.exists("p2")

    def test_snapshot_is_frozen_dataclass(self):
        snap = PlanMemorySnapshot(records=())
        with pytest.raises((AttributeError, TypeError)):
            snap.records = ()  # type: ignore

    def test_snapshot_round_trip_preserves_all_record_fields(self):
        mem = PlanMemory()
        mem.put(
            plan=make_plan(intent="i", arguments={"a": 1}),
            plan_id="p1",
            subgoal_id="sg-1",
            segments=["s1"],
            created_at="2024-01-01T00:00:00",
            metadata={"tag": "x"},
        )
        snap = mem.snapshot()
        mem2 = PlanMemory()
        mem2.load_snapshot(snap)

        record = mem2.get_record("p1")
        assert record is not None
        assert record.subgoal_id == "sg-1"
        assert record.segments == ["s1"]
        assert record.metadata == {"tag": "x"}
        assert record.arguments == {"a": 1}


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------

class TestDeterministicOrdering:
    def test_list_all_sorted_by_created_at_then_plan_id(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(), plan_id="p3", created_at="2024-01-03T00:00:00")
        put_plan(mem, make_plan(), plan_id="p1", created_at="2024-01-01T00:00:00")
        put_plan(mem, make_plan(), plan_id="p2", created_at="2024-01-02T00:00:00")

        result = mem.list_all()
        # list_all returns Plans (no plan_id), so verify via record ordering
        records = sorted(mem._store.values(), key=lambda r: (r.created_at, r.plan_id))
        assert [r.intent for r in records] == [p.intent for p in result]

    def test_list_all_stable_across_calls(self):
        mem = PlanMemory()
        for i in range(5):
            put_plan(mem, make_plan(intent=f"intent-{i}"), plan_id=f"p{i}", created_at=f"2024-01-0{i+1}T00:00:00")

        first = [p.intent for p in mem.list_all()]
        second = [p.intent for p in mem.list_all()]
        assert first == second

    def test_snapshot_records_sorted_deterministically(self):
        mem = PlanMemory()
        put_plan(mem, make_plan(), plan_id="p2", created_at="2024-01-02T00:00:00")
        put_plan(mem, make_plan(), plan_id="p1", created_at="2024-01-01T00:00:00")

        snap = mem.snapshot()
        dates = [r.created_at for r in snap.records]
        assert dates == sorted(dates)

    def test_empty_store_list_all_returns_empty(self):
        mem = PlanMemory()
        assert mem.list_all() == []

    def test_empty_store_snapshot_has_no_records(self):
        mem = PlanMemory()
        assert mem.snapshot().records == ()