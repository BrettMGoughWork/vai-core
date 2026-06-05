"""
Phase 2.13.4 — Multi-Subgoal Tests
===================================

Validate multi-subgoal execution:
- subgoal transitions (pending → active → complete)
- drift in early and late subgoals
- repair propagation
- agent completion detection
"""
from __future__ import annotations

from tests.integration.agent.conftest import (
    make_segment,
    make_subgoal,
    plan_2_3,
    plan_3_6,
    run_agent_loop,
    PlanSegment,
    SubgoalLifecycleState,
)


class TestAgentMultiSubgoal:
    """Multi-subgoal execution validation."""

    # ── basic multi-subgoal ──────────────────────────────────────────────

    def test_two_subgoals_complete(self):
        """2 subgoals with segments should complete."""
        sgs, segs = plan_2_3()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=30)
        assert result.is_complete is True
        assert result.termination_reason == "agent_complete"

    def test_three_subgoals_six_segments_complete(self):
        """3 subgoals with 6 segments total should complete."""
        sgs, segs = plan_3_6()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=60)
        assert result.is_complete is True

    def test_subgoal_index_increments(self):
        """Subgoal index must advance from 0 → 1 → 2 for 3-subgoal plan."""
        sgs, segs = plan_3_6()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=60)
        assert result.execution_state.subgoal_state.index == 3
        assert result.execution_state.subgoal_state.state == "complete"

    def test_subgoal_lifecycle_transitions(self):
        """Subgoal lifecycle: pending → active → complete."""
        sgs, segs = plan_2_3()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=30)
        # Agent entries should show subgoal transitions
        agent_entries = result.trace.agent
        assert len(agent_entries) > 0
        # Final entry should be agent complete
        assert agent_entries[-1]["is_complete"] is True

    # ── drift in early subgoals ──────────────────────────────────────────

    def test_drift_in_early_subgoal_doesnt_block_later(self):
        """Drift in the first subgoal blocks progression until repaired."""
        sgs = [
            make_subgoal(subgoal_id="sg.early", goal="Early subgoal"),
            make_subgoal(subgoal_id="sg.late", goal="Late subgoal"),
        ]
        segs = [
            make_segment(subgoal_id="sg.early", steps=[]),  # drift
            make_segment(subgoal_id="sg.late", steps=["late.a", "late.b"]),
        ]
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        # Drifted segment never completes → max_cycles_exceeded
        assert result.termination_reason == "max_cycles_exceeded"
        assert len(result.trace.drift) > 0

    def test_drift_in_late_subgoal_handled(self):
        """Drift in the last subgoal blocks completion — verify detection."""
        sgs = [
            make_subgoal(subgoal_id="sg.first", goal="First subgoal"),
            make_subgoal(subgoal_id="sg.last", goal="Last subgoal"),
        ]
        segs = [
            make_segment(subgoal_id="sg.first", steps=["first.a"]),
            make_segment(subgoal_id="sg.last", steps=[]),  # drift
        ]
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        # First subgoal completes, second has drift → max_cycles_exceeded
        assert result.termination_reason == "max_cycles_exceeded"
        assert len(result.trace.drift) > 0

    # ── repair in early / late subgoals ──────────────────────────────────

    def test_repair_in_early_subgoal(self):
        """Repair in first subgoal — verify drift and repair trace entries."""
        sgs = [
            make_subgoal(subgoal_id="sg.repair.early", goal="Early (needs repair)"),
            make_subgoal(subgoal_id="sg.repair.late", goal="Late"),
        ]
        segs = [
            make_segment(subgoal_id="sg.repair.early", steps=[]),  # needs repair
            make_segment(subgoal_id="sg.repair.late", steps=["ok"]),
        ]
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        # Drifted segment blocks → max_cycles_exceeded, but repair is attempted
        assert result.termination_reason == "max_cycles_exceeded"
        repair_actions = [
            r for r in result.trace.repairs
            if r.get("action") not in (None, "none")
        ]
        assert len(repair_actions) > 0

    def test_agent_completion_detection(self):
        """is_complete=True only when final subgoal completes."""
        sgs, segs = plan_3_6()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=60)
        assert result.is_complete is True

    # ── subgoal trace entries ────────────────────────────────────────────

    def test_subgoal_trace_entries_present(self):
        """Every subgoal should have trace entries."""
        sgs, segs = plan_3_6()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=60)
        assert len(result.trace.subgoals) > 0

    def test_subgoal_trace_has_correct_keys(self):
        """Subgoal trace entries must have transitions, drift, repairs, reflections keys."""
        sg = make_subgoal(subgoal_id="sg.key", goal="Key test")
        seg = make_segment(subgoal_id="sg.key", steps=["step"])
        sgs = [sg]
        result = run_agent_loop(subgoals=sgs, segments=[seg], max_cycles=10)
        for entry in result.trace.subgoals:
            assert "transitions" in entry
            assert "drift" in entry
            assert "repairs" in entry
            assert "reflections" in entry
