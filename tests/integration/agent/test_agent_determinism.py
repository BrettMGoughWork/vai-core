"""
Phase 2.13.4 — Determinism Tests
=================================

Validate that the agent loop is fully deterministic:
- Same plan twice → identical outputs
- Identical traces across all dimensions
"""
from __future__ import annotations

from tests.integration.agent.conftest import (
    AgentLoopResult,
    make_segment,
    make_subgoal,
    plan_1_1,
    plan_2_3,
    plan_3_6,
    plan_with_drift,
    run_agent_loop,
    to_json,
)


class TestAgentDeterminism:
    """Determinism across repeated runs of the same plan."""

    # ── single run determinism ────────────────────────────────────────────

    def test_identical_result_for_single_subgoal_single_segment(self):
        """Running the same 1-1 plan twice produces identical results."""
        sgs, segs = plan_1_1()
        r1 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        r2 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        assert r1.is_complete == r2.is_complete
        assert r1.termination_reason == r2.termination_reason
        assert r1.total_cycles == r2.total_cycles
        assert to_json(r1.trace) == to_json(r2.trace)

    def test_identical_result_for_two_subgoal_three_segment(self):
        """Running the same 2-3 plan twice produces identical results."""
        sgs, segs = plan_2_3()
        r1 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        r2 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        assert to_json(r1.trace) == to_json(r2.trace)

    def test_identical_result_for_three_subgoal_six_segment(self):
        """Running the same 3-6 plan twice produces identical results."""
        sgs, segs = plan_3_6()
        r1 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=30)
        r2 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=30)
        assert to_json(r1.trace) == to_json(r2.trace)

    # ── subgoal trace determinism ────────────────────────────────────────

    def test_subgoal_traces_identical(self):
        sgs, segs = plan_2_3()
        r1 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        r2 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        assert to_json(r1.trace.subgoals) == to_json(r2.trace.subgoals)

    # ── segment trace determinism ────────────────────────────────────────

    def test_segment_traces_identical(self):
        sgs, segs = plan_2_3()
        r1 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        r2 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        assert to_json(r1.trace.segments) == to_json(r2.trace.segments)

    # ── drift / repair / reflection determinism ──────────────────────────

    def test_drift_repair_reflection_identical(self):
        sgs, segs = plan_2_3()
        r1 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        r2 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        assert to_json(r1.trace.drift) == to_json(r2.trace.drift)
        assert to_json(r1.trace.repairs) == to_json(r2.trace.repairs)
        assert to_json(r1.trace.reflections) == to_json(r2.trace.reflections)

    # ── memory trace determinism ─────────────────────────────────────────

    def test_memory_traces_identical(self):
        sgs, segs = plan_2_3()
        r1 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        r2 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        assert to_json(r1.trace.memory) == to_json(r2.trace.memory)

    # ── plan with drift determinism ──────────────────────────────────────

    def test_plan_with_drift_identical(self):
        """Drift-introducing plans must also be deterministic."""
        sgs, segs = plan_with_drift()
        r1 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        r2 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        assert to_json(r1.trace) == to_json(r2.trace)

    # ── error trace determinism ──────────────────────────────────────────

    def test_error_traces_identical(self):
        """A plan that terminates via max_cycles must produce identical error traces."""
        sgs, segs = plan_1_1()
        r1 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=1)
        r2 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=1)
        assert to_json(r1.trace.errors) == to_json(r2.trace.errors)

    # ── full agent state determinism ─────────────────────────────────────

    def test_agent_state_identical(self):
        sgs, segs = plan_2_3()
        r1 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        r2 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        assert r1.execution_state.cycle == r2.execution_state.cycle
        assert r1.execution_state.is_complete == r2.execution_state.is_complete
        assert (
            r1.execution_state.subgoal_state.state
            == r2.execution_state.subgoal_state.state
        )
        assert (
            r1.execution_state.subgoal_state.index
            == r2.execution_state.subgoal_state.index
        )
