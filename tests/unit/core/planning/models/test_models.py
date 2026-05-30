"""Tests for src.core.types — PlanSegment and Subgoal."""
import pytest
from dataclasses import FrozenInstanceError

from src.core.types.plan_segment import PlanSegment
from src.core.types.subgoal import Subgoal

_FIXED_TS = 1_700_000_000_000  # fixed epoch ms for Subgoal hash tests
_FIXED_ISO = "2024-01-01T00:00:00"  # fixed ISO string for PlanSegment hash tests


# ── PlanSegment construction ──────────────────────────────────────────────────

class TestPlanSegmentConstruction:
    def test_minimal_construction(self):
        seg = PlanSegment(subgoal_id="goal-1", steps=["step-a", "step-b"])

        assert seg.subgoal_id == "goal-1"
        assert seg.steps == ["step-a", "step-b"]

    def test_segment_id_computed_on_construction(self):
        seg = PlanSegment(subgoal_id="goal-1", steps=["step-a"])

        assert isinstance(seg.segment_id, str)
        assert len(seg.segment_id) == 64

    def test_empty_steps_accepted(self):
        seg = PlanSegment(subgoal_id="goal-1", steps=[])

        assert seg.steps == []

    def test_context_and_metadata_stored(self):
        seg = PlanSegment(
            subgoal_id="goal-1", steps=[],
            context={"env": "prod"}, metadata={"version": 1},
        )

        assert seg.context == {"env": "prod"}
        assert seg.metadata == {"version": 1}

    def test_created_at_is_string(self):
        seg = PlanSegment(subgoal_id="goal-1", steps=[])

        assert isinstance(seg.created_at, str)
        assert len(seg.created_at) > 0

    def test_is_frozen(self):
        seg = PlanSegment(subgoal_id="goal-1", steps=[])

        with pytest.raises(FrozenInstanceError):
            seg.subgoal_id = "changed"

    def test_canonical_hash_present_after_construction(self):
        seg = PlanSegment(subgoal_id="goal-1", steps=[])

        assert isinstance(seg.canonical_hash, str)
        assert len(seg.canonical_hash) == 64


# ── PlanSegment canonical_hash ────────────────────────────────────────────────

class TestPlanSegmentCanonicalHash:
    def test_hash_is_stable_for_same_inputs(self):
        kwargs = dict(
            subgoal_id="goal-1", steps=["a"],
            context={"k": "v"}, metadata={"m": 1},
            created_at=_FIXED_ISO,
        )

        s1 = PlanSegment(**kwargs)
        s2 = PlanSegment(**kwargs)

        assert s1.canonical_hash == s2.canonical_hash

    def test_hash_differs_on_subgoal_id_change(self):
        base = dict(steps=[], context={}, metadata={}, created_at=_FIXED_ISO)

        s1 = PlanSegment(subgoal_id="goal-1", **base)
        s2 = PlanSegment(subgoal_id="goal-2", **base)

        assert s1.canonical_hash != s2.canonical_hash

    def test_hash_differs_on_steps_change(self):
        base = dict(subgoal_id="goal-1", context={}, metadata={}, created_at=_FIXED_ISO)

        s1 = PlanSegment(steps=["a"], **base)
        s2 = PlanSegment(steps=["b"], **base)

        assert s1.canonical_hash != s2.canonical_hash

    def test_hash_differs_on_context_change(self):
        base = dict(subgoal_id="goal-1", steps=[], metadata={}, created_at=_FIXED_ISO)

        s1 = PlanSegment(context={"x": 1}, **base)
        s2 = PlanSegment(context={"x": 2}, **base)

        assert s1.canonical_hash != s2.canonical_hash


# ── PlanSegment validation ────────────────────────────────────────────────────

class TestPlanSegmentValidation:
    def test_non_json_context_raises(self):
        with pytest.raises(TypeError):
            PlanSegment(
                subgoal_id="goal-1", steps=[],
                context={"key": object()}, metadata={},
            )

    def test_non_json_metadata_raises(self):
        with pytest.raises(TypeError):
            PlanSegment(
                subgoal_id="goal-1", steps=[],
                context={}, metadata={"key": set()},
            )

    def test_nested_json_context_accepted(self):
        seg = PlanSegment(
            subgoal_id="goal-1", steps=[],
            context={"outer": {"inner": [1, "two", None]}}, metadata={},
        )

        assert seg.context["outer"]["inner"] == [1, "two", None]


# ── Subgoal construction ──────────────────────────────────────────────────────

class TestSubgoalConstruction:
    def test_minimal_construction(self):
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="fetch user profile",
            context={},
            metadata={},
        )

        assert sg.subgoal_id == "sg-1"
        assert sg.goal == "fetch user profile"

    def test_parent_id_defaults_to_none(self):
        sg = Subgoal(subgoal_id="sg-1", goal="do something", context={}, metadata={})

        assert sg.parent_id is None

    def test_explicit_parent_id(self):
        sg = Subgoal(
            subgoal_id="sg-2",
            goal="child goal",
            context={},
            metadata={},
            parent_id="sg-1",
        )

        assert sg.parent_id == "sg-1"

    def test_context_and_metadata_stored(self):
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="do thing",
            context={"user": "alice"},
            metadata={"priority": 1},
        )

        assert sg.context == {"user": "alice"}
        assert sg.metadata == {"priority": 1}

    def test_created_at_is_positive_int(self):
        sg = Subgoal(subgoal_id="sg-1", goal="do thing", context={}, metadata={})

        assert isinstance(sg.created_at, int)
        assert sg.created_at > 0

    def test_is_frozen(self):
        sg = Subgoal(subgoal_id="sg-1", goal="do thing", context={}, metadata={})

        with pytest.raises(FrozenInstanceError):
            sg.goal = "changed"

    def test_canonical_hash_present_after_construction(self):
        sg = Subgoal(subgoal_id="sg-1", goal="do thing", context={}, metadata={})

        assert isinstance(sg.canonical_hash, str)
        assert len(sg.canonical_hash) == 64


# ── Subgoal canonical_hash ────────────────────────────────────────────────────

class TestSubgoalCanonicalHash:
    def test_hash_is_stable_for_same_inputs(self):
        kwargs = dict(
            subgoal_id="sg-1",
            goal="do thing",
            context={"k": "v"},
            metadata={"m": 1},
            created_at=_FIXED_TS,
        )

        sg1 = Subgoal(**kwargs)
        sg2 = Subgoal(**kwargs)

        assert sg1.canonical_hash == sg2.canonical_hash

    def test_hash_differs_on_goal_change(self):
        base = dict(subgoal_id="sg-1", context={}, metadata={}, created_at=_FIXED_TS)

        sg1 = Subgoal(goal="a", **base)
        sg2 = Subgoal(goal="b", **base)

        assert sg1.canonical_hash != sg2.canonical_hash

    def test_hash_differs_on_subgoal_id_change(self):
        base = dict(goal="g", context={}, metadata={}, created_at=_FIXED_TS)

        sg1 = Subgoal(subgoal_id="sg-1", **base)
        sg2 = Subgoal(subgoal_id="sg-2", **base)

        assert sg1.canonical_hash != sg2.canonical_hash

    def test_hash_differs_on_parent_id_change(self):
        base = dict(subgoal_id="sg-2", goal="g", context={}, metadata={}, created_at=_FIXED_TS)

        sg1 = Subgoal(parent_id=None, **base)
        sg2 = Subgoal(parent_id="sg-1", **base)

        assert sg1.canonical_hash != sg2.canonical_hash

    def test_hash_differs_on_context_change(self):
        base = dict(subgoal_id="sg-1", goal="g", metadata={}, created_at=_FIXED_TS)

        sg1 = Subgoal(context={"x": 1}, **base)
        sg2 = Subgoal(context={"x": 2}, **base)

        assert sg1.canonical_hash != sg2.canonical_hash

    def test_hash_differs_on_metadata_change(self):
        base = dict(subgoal_id="sg-1", goal="g", context={})

        sg1 = Subgoal(metadata={"a": 1}, **base)
        sg2 = Subgoal(metadata={"a": 2}, **base)

        assert sg1.canonical_hash != sg2.canonical_hash


# ── Subgoal validation ────────────────────────────────────────────────────────

class TestSubgoalValidation:
    def test_non_json_context_raises(self):
        with pytest.raises(TypeError):
            Subgoal(
                subgoal_id="sg-1",
                goal="do thing",
                context={"key": object()},
                metadata={},
            )

    def test_non_json_metadata_raises(self):
        with pytest.raises(TypeError):
            Subgoal(
                subgoal_id="sg-1",
                goal="do thing",
                context={},
                metadata={"key": set()},
            )

    def test_nested_json_structure_accepted(self):
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="do thing",
            context={"tags": ["a", "b"], "depth": 2},
            metadata={"source": None},
        )

        assert sg.context["tags"] == ["a", "b"]
        assert sg.metadata["source"] is None
