"""
Phase 2.13.4 — Long-Horizon Tests
==================================

Validate agent loop stability over longer runs:
- 20–50 cycle plans
- drift and repair every N/M cycles
- no drift at all (long clean run)
- max cycle termination
"""
from __future__ import annotations

import json

from tests.integration.agent.conftest import (
    is_json_safe,
    make_segment,
    make_subgoal,
    run_agent_loop,
)


class TestAgentLongHorizon:
    """Long-running plan stability validation."""

    # ── long clean run ───────────────────────────────────────────────────

    def test_long_clean_run_no_drift(self):
        """A plan with many clean segments completes without corruption."""
        sg = make_subgoal(subgoal_id="sg.long")
        segs = [
            make_segment(subgoal_id="sg.long", steps=[f"s{i}.a", f"s{i}.b"])
            for i in range(10)
        ]
        result = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=100)
        assert result.is_complete is True
        assert result.termination_reason == "agent_complete"
        assert is_json_safe(result.trace.to_dict())

    def test_many_subgoals_complete(self):
        """5 subgoals with 2 segments each (10 segments total) should complete."""
        sgs = [
            make_subgoal(subgoal_id=f"sg.{i}", goal=f"Subgoal {i}")
            for i in range(5)
        ]
        segs = []
        for i in range(5):
            segs.append(make_segment(subgoal_id=f"sg.{i}", steps=[f"s{i}.1"]))
            segs.append(make_segment(subgoal_id=f"sg.{i}", steps=[f"s{i}.2"]))
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=200)
        assert result.is_complete is True

    # ── drift every N cycles ─────────────────────────────────────────────

    def test_alternating_drift(self):
        """Clean → drifted → clean → drifted pattern — verify drift detection."""
        sg = make_subgoal(subgoal_id="sg.alt")
        segs = []
        for i in range(6):
            if i % 2 == 0:
                segs.append(make_segment(
                    subgoal_id="sg.alt", steps=[f"clean.{i}"]
                ))
            else:
                segs.append(make_segment(
                    subgoal_id="sg.alt", steps=[]  # drift
                ))
        result = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=60)
        # First segment (clean) completes, then drift blocks
        assert result.termination_reason == "max_cycles_exceeded"
        assert len(result.trace.drift) > 0

    def test_consecutive_drift(self):
        """Multiple drifted segments in a row — verify drift detection."""
        sg = make_subgoal(subgoal_id="sg.cdrift")
        segs = [
            make_segment(subgoal_id="sg.cdrift", steps=[]),  # drift
            make_segment(subgoal_id="sg.cdrift", steps=[]),  # drift
            make_segment(subgoal_id="sg.cdrift", steps=["final"]),  # clean
        ]
        result = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=30)
        # First drifted segment blocks
        assert result.termination_reason == "max_cycles_exceeded"
        assert len(result.trace.drift) > 0

    # ── max cycle termination ────────────────────────────────────────────

    def test_max_cycle_termination(self):
        """Agent loop stops at max_cycles."""
        sg = make_subgoal(subgoal_id="sg.max")
        # Many segments to ensure we hit max_cycles before completion
        segs = [
            make_segment(subgoal_id="sg.max", steps=[f"step.{i}"])
            for i in range(50)
        ]
        result = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=5)
        assert result.termination_reason == "max_cycles_exceeded"
        assert result.is_complete is False

    def test_max_cycle_trace_intact(self):
        """Trace must be valid even on max_cycle termination."""
        sg = make_subgoal(subgoal_id="sg.maxtrace")
        segs = [
            make_segment(subgoal_id="sg.maxtrace", steps=[f"s{i}"])
            for i in range(50)
        ]
        result = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=5)
        assert is_json_safe(result.trace.to_dict())
        assert result.total_cycles == 5
        assert len(result.trace.cycles) <= 5

    # ── no memory leaks / state corruption ───────────────────────────────

    def test_trace_grows_proportionally(self):
        """Trace size grows proportionally with cycles, not exponentially."""
        sg = make_subgoal(subgoal_id="sg.grow")
        segs = [
            make_segment(subgoal_id="sg.grow", steps=[f"s{i}"])
            for i in range(20)
        ]
        r1 = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=5)
        r2 = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=10)
        # Memory snapshots should scale roughly linearly
        assert len(r2.trace.memory) <= len(r1.trace.memory) * 2 + 2

    def test_trace_remains_deterministic_after_long_run(self):
        """Long runs must still be deterministic."""
        sg = make_subgoal(subgoal_id="sg.detlong")
        segs = [
            make_segment(subgoal_id="sg.detlong", steps=[f"det.{i}"])
            for i in range(10)
        ]
        r1 = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=50)
        r2 = run_agent_loop(subgoals=[sg], segments=segs, max_cycles=50)
        assert r1.total_cycles == r2.total_cycles
        assert r1.trace.cycles == r2.trace.cycles
