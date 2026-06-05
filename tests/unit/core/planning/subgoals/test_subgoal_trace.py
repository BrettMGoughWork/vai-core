"""
Tests for Phase 2.12.4 — Subgoal Trace (``src.core.planning.subgoals.trace``).
"""
from __future__ import annotations

import json

import pytest

from src.core.planning.subgoals.drift import (
    SubgoalDriftResult,
)
from src.core.planning.subgoals.execution import (
    SubgoalExecutionPhase,
    SubgoalExecutionState,
)
from src.core.planning.subgoals.reflection import (
    SubgoalReflectionResult,
)
from src.core.planning.subgoals.trace import (
    SubgoalTrace,
    build_subgoal_trace,
    execute_subgoal_cycle,
)
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_subgoal(
    subgoal_id: str = "sg.test",
    goal: str = "Test goal",
    context: dict | None = None,
    metadata: dict | None = None,
    parent_id: str | None = None,
    state: SubgoalLifecycleState = SubgoalLifecycleState.ACTIVE,
) -> Subgoal:
    """Create a minimal valid Subgoal for testing."""
    if context is None:
        context = {"key": "value"}
    if metadata is None:
        metadata = {}
    return Subgoal(
        subgoal_id=subgoal_id,
        goal=goal,
        context=context,
        metadata=metadata,
        parent_id=parent_id,
        state=state,
    )


def _is_json_safe(obj: object) -> bool:
    """Check that an object is JSON‑serialisable."""
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


def _trace_to_dict(trace: SubgoalTrace) -> dict:
    """Convert SubgoalTrace to JSON‑safe dict for comparison."""
    return {
        "transitions": trace.transitions,
        "drift": trace.drift,
        "repairs": trace.repairs,
        "reflections": trace.reflections,
    }


# ──────────────────────────────────────────────────────────────────────────────
# SubgoalTrace dataclass
# ──────────────────────────────────────────────────────────────────────────────


class TestSubgoalTrace:
    """Tests for the SubgoalTrace frozen dataclass."""

    def test_construction_with_empty_lists(self):
        """SubgoalTrace constructs with all empty lists."""
        t = SubgoalTrace(
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
        """SubgoalTrace constructs with populated lists."""
        t = SubgoalTrace(
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
        """SubgoalTrace is immutable."""
        t = SubgoalTrace(transitions=[], drift=[], repairs=[], reflections=[])
        with pytest.raises(Exception):
            t.transitions = [{}]  # type: ignore[misc]

    def test_json_safe(self):
        """All SubgoalTrace fields and the full trace are JSON‑serialisable."""
        t = SubgoalTrace(
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
                    "progress": {"segment_count": 1},
                    "drift": {"status": "no_drift", "severity": "minor"},
                    "repair": {"action": "none"},
                    "is_complete": True,
                }
            ],
        )
        assert _is_json_safe(_trace_to_dict(t))

    def test_deterministic_equality(self):
        """Identical inputs produce equal SubgoalTrace instances."""
        t1 = SubgoalTrace(
            transitions=[{"a": 1}], drift=[], repairs=[], reflections=[]
        )
        t2 = SubgoalTrace(
            transitions=[{"a": 1}], drift=[], repairs=[], reflections=[]
        )
        assert t1 == t2
        assert hash(t1) == hash(t2)

    def test_hash_stable(self):
        """Hash is stable across repeated calls."""
        t = SubgoalTrace(
            transitions=[{"x": "y"}],
            drift=[{"z": 1}],
            repairs=[{"action": "none"}],
            reflections=[{"ok": True}],
        )
        h1 = hash(t)
        h2 = hash(t)
        assert h1 == h2


# ──────────────────────────────────────────────────────────────────────────────
# build_subgoal_trace
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildSubgoalTrace:
    """Tests for build_subgoal_trace — the pure trace aggregator."""

    def _make_states(self, from_idx=0, from_st="active", to_idx=0, to_st="active"):
        exec_state = SubgoalExecutionState(index=from_idx, state=from_st)
        new_exec_state = SubgoalExecutionState(index=to_idx, state=to_st)
        return exec_state, new_exec_state

    def _make_drift_result(self, action="none"):
        return SubgoalDriftResult(
            drift={"status": "no_drift", "severity": "minor"},
            action=action,
            repaired_subgoal={"subgoal_id": "s1", "goal": "x", "context": {}},
            requires_replan=(action == "replan_subgoal"),
        )

    def _make_reflection(self, is_complete=True):
        return SubgoalReflectionResult(
            progress={"segment_count": 1},
            drift={"status": "no_drift", "severity": "minor"},
            repair={"action": "none"},
            is_complete=is_complete,
        )

    def test_builds_transition_entry(self):
        """Transition entry records from_state, to_state, and indices."""
        sg = _make_subgoal()
        exec_state, new_exec = self._make_states(
            from_idx=0, from_st="pending", to_idx=0, to_st="active"
        )
        drift_result = self._make_drift_result()
        reflection = self._make_reflection()

        trace = build_subgoal_trace(exec_state, sg, reflection, drift_result, new_exec)

        assert len(trace.transitions) == 1
        t = trace.transitions[0]
        assert t["from_state"] == "pending"
        assert t["to_state"] == "active"
        assert t["index_before"] == 0
        assert t["index_after"] == 0

    def test_builds_drift_entry(self):
        """Drift entry records drift dict, action, and requires_replan."""
        sg = _make_subgoal()
        exec_state, new_exec = self._make_states()
        drift_result = SubgoalDriftResult(
            drift={"status": "drift_detected", "severity": "major"},
            action="repair_subgoal",
            repaired_subgoal={"subgoal_id": "s1", "goal": "fixed", "context": {}},
            requires_replan=False,
        )
        reflection = self._make_reflection()

        trace = build_subgoal_trace(exec_state, sg, reflection, drift_result, new_exec)

        assert len(trace.drift) == 1
        d = trace.drift[0]
        assert d["drift"]["status"] == "drift_detected"
        assert d["action"] == "repair_subgoal"
        assert d["requires_replan"] is False

    def test_builds_repair_entry_for_repair_action(self):
        """Repair entry includes repaired_subgoal when action is repair_subgoal."""
        sg = _make_subgoal()
        exec_state, new_exec = self._make_states()
        drift_result = SubgoalDriftResult(
            drift={"status": "drift_detected", "severity": "minor"},
            action="repair_subgoal",
            repaired_subgoal={"subgoal_id": "repaired", "goal": "x", "context": {}},
            requires_replan=False,
        )
        reflection = self._make_reflection()

        trace = build_subgoal_trace(exec_state, sg, reflection, drift_result, new_exec)

        assert len(trace.repairs) == 1
        r = trace.repairs[0]
        assert r["action"] == "repair_subgoal"
        assert "repaired_subgoal" in r

    def test_builds_repair_entry_for_none_action(self):
        """Repair entry is minimal when action is 'none'."""
        sg = _make_subgoal()
        exec_state, new_exec = self._make_states()
        drift_result = self._make_drift_result(action="none")
        reflection = self._make_reflection()

        trace = build_subgoal_trace(exec_state, sg, reflection, drift_result, new_exec)

        assert len(trace.repairs) == 1
        r = trace.repairs[0]
        assert r["action"] == "none"
        assert "repaired_subgoal" not in r

    def test_builds_replan_repair_entry(self):
        """Repair entry is minimal when action is 'replan_subgoal'."""
        sg = _make_subgoal()
        exec_state, new_exec = self._make_states()
        drift_result = self._make_drift_result(action="replan_subgoal")
        reflection = self._make_reflection()

        trace = build_subgoal_trace(exec_state, sg, reflection, drift_result, new_exec)

        assert len(trace.repairs) == 1
        r = trace.repairs[0]
        assert r["action"] == "replan_subgoal"
        assert "repaired_subgoal" not in r

    def test_builds_reflection_entry(self):
        """Reflection entry records progress, drift, repair, and is_complete."""
        sg = _make_subgoal()
        exec_state, new_exec = self._make_states()
        drift_result = self._make_drift_result()
        reflection = self._make_reflection(is_complete=False)

        trace = build_subgoal_trace(exec_state, sg, reflection, drift_result, new_exec)

        assert len(trace.reflections) == 1
        ref = trace.reflections[0]
        assert "progress" in ref
        assert "drift" in ref
        assert "repair" in ref
        assert ref["is_complete"] is False

    def test_deterministic(self):
        """Same inputs produce identical trace."""
        sg = _make_subgoal()
        exec_state, new_exec = self._make_states()
        drift_result = self._make_drift_result()
        reflection = self._make_reflection()

        t1 = build_subgoal_trace(exec_state, sg, reflection, drift_result, new_exec)
        t2 = build_subgoal_trace(exec_state, sg, reflection, drift_result, new_exec)

        assert t1 == t2
        assert hash(t1) == hash(t2)

    def test_does_not_mutate_inputs(self):
        """Input objects are not modified by build_subgoal_trace."""
        sg = _make_subgoal(subgoal_id="original")
        exec_state, new_exec = self._make_states()
        drift_result = self._make_drift_result()
        reflection = self._make_reflection()

        exec_state_copy = SubgoalExecutionState(
            index=exec_state.index, state=exec_state.state
        )

        build_subgoal_trace(exec_state, sg, reflection, drift_result, new_exec)

        assert exec_state == exec_state_copy
        assert sg.subgoal_id == "original"


# ──────────────────────────────────────────────────────────────────────────────
# execute_subgoal_cycle (orchestrator)
# ──────────────────────────────────────────────────────────────────────────────


class TestExecuteSubgoalCycle:
    """Tests for execute_subgoal_cycle — the full pipeline orchestrator."""

    def test_returns_expected_keys(self):
        """Result dict has execution_state, subgoal, and subgoal_trace."""
        sg = _make_subgoal()
        exec_state = SubgoalExecutionState(index=0, state="pending")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)

        assert "execution_state" in result
        assert "subgoal" in result
        assert "subgoal_trace" in result

    def test_pending_transitions_to_active(self):
        """Pending subgoal transitions to active."""
        sg = _make_subgoal()
        exec_state = SubgoalExecutionState(index=0, state="pending")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)

        new_state = result["execution_state"]
        assert new_state.state == SubgoalExecutionPhase.ACTIVE

    def test_active_stays_active_if_not_complete(self):
        """Active subgoal that is not complete stays active."""
        sg = _make_subgoal(goal="")
        exec_state = SubgoalExecutionState(index=0, state="active")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)

        new_state = result["execution_state"]
        assert new_state.state == SubgoalExecutionPhase.ACTIVE

    def test_active_transitions_to_complete_if_complete(self):
        """Complete active subgoal transitions to complete."""
        sg = _make_subgoal()
        exec_state = SubgoalExecutionState(index=0, state="active")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)

        new_state = result["execution_state"]
        assert new_state.state == SubgoalExecutionPhase.COMPLETE

    def test_complete_advances_index(self):
        """When subgoal completes, index advances if more subgoals exist."""
        sg = _make_subgoal()
        exec_state = SubgoalExecutionState(index=0, state="active")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=3)

        new_state = result["execution_state"]
        assert new_state.state == SubgoalExecutionPhase.COMPLETE
        assert new_state.index == 1

    def test_transition_trace_present(self):
        """Trace includes a transition entry."""
        sg = _make_subgoal()
        exec_state = SubgoalExecutionState(index=0, state="pending")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)

        trace = result["subgoal_trace"]
        assert len(trace.transitions) == 1
        t = trace.transitions[0]
        assert t["from_state"] == "pending"
        assert t["to_state"] == "active"

    def test_drift_trace_present(self):
        """Trace includes a drift entry."""
        sg = _make_subgoal(goal="")
        exec_state = SubgoalExecutionState(index=0, state="active")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)

        trace = result["subgoal_trace"]
        assert len(trace.drift) == 1
        assert "drift" in trace.drift[0]
        assert "action" in trace.drift[0]

    def test_repair_trace_present(self):
        """Trace includes a repair entry."""
        sg = _make_subgoal(goal="")
        exec_state = SubgoalExecutionState(index=0, state="active")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)

        trace = result["subgoal_trace"]
        assert len(trace.repairs) == 1
        assert "action" in trace.repairs[0]

    def test_reflection_trace_present(self):
        """Trace includes a reflection entry."""
        sg = _make_subgoal()
        exec_state = SubgoalExecutionState(index=0, state="pending")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)

        trace = result["subgoal_trace"]
        assert len(trace.reflections) == 1
        ref = trace.reflections[0]
        assert "progress" in ref
        assert "drift" in ref
        assert "repair" in ref
        assert "is_complete" in ref

    def test_trace_ordering(self):
        """Trace entries are populated in pipeline order."""
        sg = _make_subgoal()
        exec_state = SubgoalExecutionState(index=0, state="pending")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)

        trace = result["subgoal_trace"]
        assert len(trace.transitions) >= 1
        assert len(trace.drift) >= 1
        assert len(trace.repairs) >= 1
        assert len(trace.reflections) >= 1

    def test_deterministic(self):
        """Same inputs produce identical cycle results."""
        sg = _make_subgoal()
        exec_state = SubgoalExecutionState(index=0, state="pending")

        r1 = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)
        r2 = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)

        assert r1["execution_state"] == r2["execution_state"]
        assert r1["subgoal"] == r2["subgoal"]
        assert r1["subgoal_trace"] == r2["subgoal_trace"]

    def test_json_safe_output(self):
        """Full cycle output is JSON‑safe."""
        sg = _make_subgoal()
        exec_state = SubgoalExecutionState(index=0, state="pending")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)

        output = {
            "execution_state": {
                "index": result["execution_state"].index,
                "state": result["execution_state"].state,
            },
            "subgoal": result["subgoal"],
            "subgoal_trace": _trace_to_dict(result["subgoal_trace"]),
        }
        assert _is_json_safe(output)

    def test_malformed_subgoal_cycle_works(self):
        """Malformed subgoal still produces a trace (no crash)."""
        sg = _make_subgoal(subgoal_id="", goal="")
        exec_state = SubgoalExecutionState(index=0, state="active")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=1)

        assert "execution_state" in result
        assert "subgoal" in result
        assert "subgoal_trace" in result
        trace = result["subgoal_trace"]
        assert len(trace.drift) >= 1

    def test_complete_terminal_does_not_advance_further(self):
        """Already-complete state stays complete, index unchanged."""
        sg = _make_subgoal()
        exec_state = SubgoalExecutionState(index=1, state="complete")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=3)

        new_state = result["execution_state"]
        assert new_state.state == SubgoalExecutionPhase.COMPLETE
        assert new_state.index == 1

    def test_transition_trace_has_correct_indices(self):
        """Transition trace captures correct index_before and index_after."""
        sg = _make_subgoal()
        exec_state = SubgoalExecutionState(index=0, state="active")
        result = execute_subgoal_cycle(exec_state, sg, total_subgoals=3)

        trace = result["subgoal_trace"]
        t = trace.transitions[0]
        assert t["index_before"] == 0
        assert t["index_after"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# Integration: multiple cycles
# ──────────────────────────────────────────────────────────────────────────────


class TestMultipleCycles:
    """Tests for running multiple subgoal cycles in sequence."""

    def test_two_cycles_advance_through_subgoals(self):
        """Two sequential cycles advance through both subgoals."""
        sg = _make_subgoal()
        exec_state = SubgoalExecutionState(index=0, state="pending")

        # Cycle 1: pending → active → complete → index 1
        r1 = execute_subgoal_cycle(exec_state, sg, total_subgoals=2)
        assert r1["execution_state"].state == SubgoalExecutionPhase.ACTIVE

        # Cycle 2: active at index 0 → complete → index 1
        exec2 = SubgoalExecutionState(
            index=r1["execution_state"].index, state="active"
        )
        r2 = execute_subgoal_cycle(exec2, sg, total_subgoals=2)
        assert r2["execution_state"].state == SubgoalExecutionPhase.COMPLETE
        assert r2["execution_state"].index == 1
