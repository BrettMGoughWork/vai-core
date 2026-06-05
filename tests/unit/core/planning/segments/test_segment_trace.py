"""
Tests for Phase 2.11.4 — Segment Trace (``src.core.planning.segments.trace``).
"""
from __future__ import annotations

import json

import pytest

from src.core.planning.segments.drift import SegmentDriftResult
from src.core.planning.segments.execution import SegmentExecutionState, SegmentLifecycle
from src.core.planning.segments.reflection import (
    SegmentReflectionResult,
    reflect_on_segment,
)
from src.core.planning.segments.trace import (
    SegmentTrace,
    build_segment_trace,
    execute_segment_cycle,
)
from src.core.types.plan_segment import PlanSegment


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_segment(
    subgoal_id: str = "sub.test",
    steps: list | None = None,
    context: dict | None = None,
) -> PlanSegment:
    """Create a minimal valid PlanSegment for testing."""
    if steps is None:
        steps = ["noop"]
    if context is None:
        context = {}
    return PlanSegment(
        subgoal_id=subgoal_id,
        steps=steps,
        context=context,
        metadata={},
    )


def _is_json_safe(obj: object) -> bool:
    """Check that an object is JSON‑serialisable."""
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


def _trace_to_dict(trace: SegmentTrace) -> dict:
    """Convert SegmentTrace to JSON‑safe dict for comparison."""
    return {
        "transitions": trace.transitions,
        "drift": trace.drift,
        "repairs": trace.repairs,
        "reflections": trace.reflections,
    }


# ──────────────────────────────────────────────────────────────────────────────
# SegmentTrace dataclass
# ──────────────────────────────────────────────────────────────────────────────


class TestSegmentTrace:
    """Tests for the SegmentTrace frozen dataclass."""

    def test_construction_with_empty_lists(self):
        """SegmentTrace constructs with all empty lists."""
        t = SegmentTrace(
            transitions=[],
            drift=[],
            repairs=[],
            reflections=[],
        )
        assert t.transitions == []
        assert t.drift == []
        assert t.repairs == []
        assert t.reflections == []

    def test_construction_with_entries(self):
        """SegmentTrace constructs with populated lists."""
        t = SegmentTrace(
            transitions=[{"from_state": "active", "to_state": "complete"}],
            drift=[{"drift": {}, "action": "none", "requires_replan": False}],
            repairs=[{"action": "none"}],
            reflections=[{"progress": {}, "drift": {}, "repair": {}, "is_complete": True}],
        )
        assert len(t.transitions) == 1
        assert len(t.drift) == 1
        assert len(t.repairs) == 1
        assert len(t.reflections) == 1

    def test_is_frozen(self):
        """SegmentTrace is immutable."""
        t = SegmentTrace(transitions=[], drift=[], repairs=[], reflections=[])
        with pytest.raises(Exception):
            t.transitions = [{}]  # type: ignore[misc]

    def test_json_safe(self):
        """All SegmentTrace fields and the full trace are JSON‑serialisable."""
        t = SegmentTrace(
            transitions=[
                {
                    "from_state": "pending",
                    "to_state": "active",
                    "index_before": 0,
                    "index_after": 0,
                }
            ],
            drift=[
                {
                    "drift": {"status": "no_drift", "severity": "minor"},
                    "action": "none",
                    "requires_replan": False,
                }
            ],
            repairs=[{"action": "none"}],
            reflections=[
                {
                    "progress": {"step_count": 1},
                    "drift": {"status": "no_drift", "severity": "minor"},
                    "repair": {"action": "none"},
                    "is_complete": True,
                }
            ],
        )
        assert _is_json_safe(_trace_to_dict(t))

    def test_deterministic_equality(self):
        """Identical inputs produce equal SegmentTrace instances."""
        t1 = SegmentTrace(
            transitions=[{"a": 1}], drift=[], repairs=[], reflections=[]
        )
        t2 = SegmentTrace(
            transitions=[{"a": 1}], drift=[], repairs=[], reflections=[]
        )
        assert t1 == t2
        assert hash(t1) == hash(t2)

    def test_hash_stable(self):
        """Hash is stable across repeated calls."""
        t = SegmentTrace(
            transitions=[{"x": "y"}],
            drift=[{"z": 1}],
            repairs=[{"action": "none"}],
            reflections=[{"ok": True}],
        )
        h1 = hash(t)
        h2 = hash(t)
        assert h1 == h2


# ──────────────────────────────────────────────────────────────────────────────
# build_segment_trace
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildSegmentTrace:
    """Tests for build_segment_trace — the pure trace aggregator."""

    def _make_states(self, from_idx=0, from_st="active", to_idx=0, to_st="active"):
        exec_state = SegmentExecutionState(index=from_idx, state=from_st)
        new_exec_state = SegmentExecutionState(index=to_idx, state=to_st)
        return exec_state, new_exec_state

    def _make_drift_result(self, action="none"):
        return SegmentDriftResult(
            drift={"status": "no_drift", "severity": "minor"},
            action=action,
            repaired_segment={"subgoal_id": "s1", "steps": ["noop"]},
            requires_replan=(action == "replan_segment"),
        )

    def _make_reflection(self, is_complete=True):
        return SegmentReflectionResult(
            progress={"step_count": 1},
            drift={"status": "no_drift", "severity": "minor"},
            repair={"action": "none"},
            is_complete=is_complete,
        )

    def test_builds_transition_entry(self):
        """Transition entry records from_state, to_state, and indices."""
        seg = _make_segment()
        exec_state, new_exec = self._make_states(
            from_idx=0, from_st="pending", to_idx=0, to_st="active"
        )
        drift_result = self._make_drift_result()
        reflection = self._make_reflection()

        trace = build_segment_trace(exec_state, seg, reflection, drift_result, new_exec)

        assert len(trace.transitions) == 1
        t = trace.transitions[0]
        assert t["from_state"] == "pending"
        assert t["to_state"] == "active"
        assert t["index_before"] == 0
        assert t["index_after"] == 0

    def test_builds_drift_entry(self):
        """Drift entry records drift dict, action, and requires_replan."""
        seg = _make_segment()
        exec_state, new_exec = self._make_states()
        drift_result = SegmentDriftResult(
            drift={"status": "drift_detected", "severity": "major"},
            action="repair_segment",
            repaired_segment={"subgoal_id": "s1", "steps": ["fixed"]},
            requires_replan=False,
        )
        reflection = self._make_reflection()

        trace = build_segment_trace(exec_state, seg, reflection, drift_result, new_exec)

        assert len(trace.drift) == 1
        d = trace.drift[0]
        assert d["drift"]["status"] == "drift_detected"
        assert d["action"] == "repair_segment"
        assert d["requires_replan"] is False

    def test_builds_repair_entry_for_repair_action(self):
        """Repair entry includes repaired_segment when action is repair_segment."""
        seg = _make_segment()
        exec_state, new_exec = self._make_states()
        drift_result = SegmentDriftResult(
            drift={"status": "drift_detected", "severity": "minor"},
            action="repair_segment",
            repaired_segment={"subgoal_id": "repaired", "steps": ["x"]},
            requires_replan=False,
        )
        reflection = self._make_reflection()

        trace = build_segment_trace(exec_state, seg, reflection, drift_result, new_exec)

        assert len(trace.repairs) == 1
        r = trace.repairs[0]
        assert r["action"] == "repair_segment"
        assert "repaired_segment" in r

    def test_builds_repair_entry_for_none_action(self):
        """Repair entry is minimal when action is 'none'."""
        seg = _make_segment()
        exec_state, new_exec = self._make_states()
        drift_result = self._make_drift_result(action="none")
        reflection = self._make_reflection()

        trace = build_segment_trace(exec_state, seg, reflection, drift_result, new_exec)

        assert len(trace.repairs) == 1
        r = trace.repairs[0]
        assert r["action"] == "none"
        assert "repaired_segment" not in r

    def test_builds_replan_repair_entry(self):
        """Repair entry is minimal when action is 'replan_segment'."""
        seg = _make_segment()
        exec_state, new_exec = self._make_states()
        drift_result = self._make_drift_result(action="replan_segment")
        reflection = self._make_reflection()

        trace = build_segment_trace(exec_state, seg, reflection, drift_result, new_exec)

        assert len(trace.repairs) == 1
        r = trace.repairs[0]
        assert r["action"] == "replan_segment"
        assert "repaired_segment" not in r

    def test_builds_reflection_entry(self):
        """Reflection entry records progress, drift, repair, and is_complete."""
        seg = _make_segment()
        exec_state, new_exec = self._make_states()
        drift_result = self._make_drift_result()
        reflection = self._make_reflection(is_complete=False)

        trace = build_segment_trace(exec_state, seg, reflection, drift_result, new_exec)

        assert len(trace.reflections) == 1
        ref = trace.reflections[0]
        assert "progress" in ref
        assert "drift" in ref
        assert "repair" in ref
        assert ref["is_complete"] is False

    def test_deterministic(self):
        """Same inputs produce identical trace."""
        seg = _make_segment()
        exec_state, new_exec = self._make_states()
        drift_result = self._make_drift_result()
        reflection = self._make_reflection()

        t1 = build_segment_trace(exec_state, seg, reflection, drift_result, new_exec)
        t2 = build_segment_trace(exec_state, seg, reflection, drift_result, new_exec)

        assert t1 == t2
        assert hash(t1) == hash(t2)

    def test_does_not_mutate_inputs(self):
        """Input objects are not modified by build_segment_trace."""
        seg = _make_segment(subgoal_id="original")
        exec_state, new_exec = self._make_states()
        drift_result = self._make_drift_result()
        reflection = self._make_reflection()

        exec_state_copy = SegmentExecutionState(
            index=exec_state.index, state=exec_state.state
        )

        build_segment_trace(exec_state, seg, reflection, drift_result, new_exec)

        assert exec_state == exec_state_copy
        assert seg.subgoal_id == "original"


# ──────────────────────────────────────────────────────────────────────────────
# execute_segment_cycle (orchestrator)
# ──────────────────────────────────────────────────────────────────────────────


class TestExecuteSegmentCycle:
    """Tests for execute_segment_cycle — the full pipeline orchestrator."""

    def test_returns_expected_keys(self):
        """Result dict has execution_state, segment, and segment_trace."""
        seg = _make_segment()
        exec_state = SegmentExecutionState(index=0, state="pending")
        result = execute_segment_cycle(exec_state, seg, total_segments=1)

        assert "execution_state" in result
        assert "segment" in result
        assert "segment_trace" in result

    def test_pending_transitions_to_active(self):
        """Pending segment transitions to active."""
        seg = _make_segment()
        exec_state = SegmentExecutionState(index=0, state="pending")
        result = execute_segment_cycle(exec_state, seg, total_segments=1)

        new_state = result["execution_state"]
        assert new_state.state == SegmentLifecycle.ACTIVE

    def test_active_stays_active_if_not_complete(self):
        """Active segment that is not complete stays active."""
        # A segment with missing subgoal_id is not complete
        seg = _make_segment(subgoal_id="")
        exec_state = SegmentExecutionState(index=0, state="active")
        result = execute_segment_cycle(exec_state, seg, total_segments=1)

        new_state = result["execution_state"]
        assert new_state.state == SegmentLifecycle.ACTIVE

    def test_active_transitions_to_complete_if_complete(self):
        """Complete active segment transitions to complete."""
        seg = _make_segment()
        exec_state = SegmentExecutionState(index=0, state="active")
        result = execute_segment_cycle(exec_state, seg, total_segments=1)

        new_state = result["execution_state"]
        assert new_state.state == SegmentLifecycle.COMPLETE

    def test_complete_advances_index(self):
        """When segment completes, index advances if more segments exist."""
        seg = _make_segment()
        exec_state = SegmentExecutionState(index=0, state="active")
        result = execute_segment_cycle(exec_state, seg, total_segments=3)

        new_state = result["execution_state"]
        assert new_state.state == SegmentLifecycle.COMPLETE
        assert new_state.index == 1

    def test_transition_trace_present(self):
        """Trace includes a transition entry."""
        seg = _make_segment()
        exec_state = SegmentExecutionState(index=0, state="pending")
        result = execute_segment_cycle(exec_state, seg, total_segments=1)

        trace = result["segment_trace"]
        assert len(trace.transitions) == 1
        t = trace.transitions[0]
        assert t["from_state"] == "pending"
        assert t["to_state"] == "active"

    def test_drift_trace_present(self):
        """Trace includes a drift entry."""
        seg = _make_segment(subgoal_id="")
        exec_state = SegmentExecutionState(index=0, state="active")
        result = execute_segment_cycle(exec_state, seg, total_segments=1)

        trace = result["segment_trace"]
        assert len(trace.drift) == 1
        assert "drift" in trace.drift[0]
        assert "action" in trace.drift[0]

    def test_repair_trace_present(self):
        """Trace includes a repair entry."""
        seg = _make_segment(subgoal_id="")
        exec_state = SegmentExecutionState(index=0, state="active")
        result = execute_segment_cycle(exec_state, seg, total_segments=1)

        trace = result["segment_trace"]
        assert len(trace.repairs) == 1
        assert "action" in trace.repairs[0]

    def test_reflection_trace_present(self):
        """Trace includes a reflection entry."""
        seg = _make_segment()
        exec_state = SegmentExecutionState(index=0, state="pending")
        result = execute_segment_cycle(exec_state, seg, total_segments=1)

        trace = result["segment_trace"]
        assert len(trace.reflections) == 1
        ref = trace.reflections[0]
        assert "progress" in ref
        assert "drift" in ref
        assert "repair" in ref
        assert "is_complete" in ref

    def test_trace_ordering(self):
        """Trace entries are populated in pipeline order."""
        seg = _make_segment()
        exec_state = SegmentExecutionState(index=0, state="pending")
        result = execute_segment_cycle(exec_state, seg, total_segments=1)

        trace = result["segment_trace"]
        # All four trace categories present
        assert len(trace.transitions) >= 1
        assert len(trace.drift) >= 1
        assert len(trace.repairs) >= 1
        assert len(trace.reflections) >= 1

    def test_deterministic(self):
        """Same inputs produce identical cycle results."""
        seg = _make_segment()
        exec_state = SegmentExecutionState(index=0, state="pending")

        r1 = execute_segment_cycle(exec_state, seg, total_segments=1)
        r2 = execute_segment_cycle(exec_state, seg, total_segments=1)

        assert r1["execution_state"] == r2["execution_state"]
        assert r1["segment"] == r2["segment"]
        assert r1["segment_trace"] == r2["segment_trace"]

    def test_json_safe_output(self):
        """Full cycle output is JSON‑safe."""
        seg = _make_segment()
        exec_state = SegmentExecutionState(index=0, state="pending")
        result = execute_segment_cycle(exec_state, seg, total_segments=1)

        output = {
            "execution_state": {
                "index": result["execution_state"].index,
                "state": result["execution_state"].state,
            },
            "segment": result["segment"],
            "segment_trace": _trace_to_dict(result["segment_trace"]),
        }
        assert _is_json_safe(output)

    def test_malformed_segment_cycle_works(self):
        """Malformed segment still produces a trace (no crash)."""
        seg = _make_segment(subgoal_id="", steps=[])
        exec_state = SegmentExecutionState(index=0, state="active")
        result = execute_segment_cycle(exec_state, seg, total_segments=1)

        assert "execution_state" in result
        assert "segment" in result
        assert "segment_trace" in result
        # Should have drift → repair action
        trace = result["segment_trace"]
        assert len(trace.drift) >= 1

    def test_complete_terminal_does_not_advance_further(self):
        """Already-complete state stays complete, index unchanged."""
        seg = _make_segment()
        exec_state = SegmentExecutionState(index=1, state="complete")
        result = execute_segment_cycle(exec_state, seg, total_segments=3)

        new_state = result["execution_state"]
        assert new_state.state == SegmentLifecycle.COMPLETE
        assert new_state.index == 1  # no further advancement

    def test_transition_trace_has_correct_indices(self):
        """Transition trace captures correct index_before and index_after."""
        seg = _make_segment()
        exec_state = SegmentExecutionState(index=0, state="active")
        result = execute_segment_cycle(exec_state, seg, total_segments=3)

        trace = result["segment_trace"]
        t = trace.transitions[0]
        assert t["index_before"] == 0
        assert t["index_after"] == 1  # advanced after completion


# ──────────────────────────────────────────────────────────────────────────────
# Integration: multiple cycles
# ──────────────────────────────────────────────────────────────────────────────


class TestMultipleCycles:
    """Tests for running multiple segment cycles in sequence."""

    def test_two_cycles_advance_through_segments(self):
        """Two sequential cycles advance through both segments."""
        seg = _make_segment()
        exec_state = SegmentExecutionState(index=0, state="pending")

        # Cycle 1: pending → active → complete → index 1
        r1 = execute_segment_cycle(exec_state, seg, total_segments=2)
        assert r1["execution_state"].state == SegmentLifecycle.ACTIVE

        # Cycle 2: (needs a new active state from index 1)
        exec2 = SegmentExecutionState(
            index=r1["execution_state"].index, state="active"
        )
        r2 = execute_segment_cycle(exec2, seg, total_segments=2)
        assert r2["execution_state"].state == SegmentLifecycle.COMPLETE
        assert r2["execution_state"].index == 1
