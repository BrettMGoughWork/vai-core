"""
Phase 2.13.4 — Trace Structure Tests
======================================

Validate that the AgentFullTrace contains all required fields
with correct structure, ordering, and JSON-safety.
"""
from __future__ import annotations

from tests.integration.agent.conftest import (
    AgentFullTrace,
    is_json_safe,
    plan_1_1,
    plan_2_3,
    plan_with_drift,
    run_agent_loop,
    trace_keys,
)


class TestAgentTraceStructure:
    """Validate full trace structure correctness."""

    # ── required fields ──────────────────────────────────────────────────

    def test_agent_full_trace_has_all_required_fields(self):
        """AgentFullTrace must contain all 9 required fields."""
        sgs, segs = plan_2_3()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        expected_keys = set(trace_keys(result.trace))
        trace_dict = result.trace.to_dict()
        for k in expected_keys:
            assert k in trace_dict, f"Missing required key: {k}"

    def test_cycles_field_is_list(self):
        sgs, segs = plan_1_1()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        assert isinstance(result.trace.cycles, list)

    def test_agent_field_is_list(self):
        sgs, segs = plan_1_1()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        assert isinstance(result.trace.agent, list)

    def test_subgoals_field_is_list(self):
        sgs, segs = plan_1_1()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        assert isinstance(result.trace.subgoals, list)

    def test_segments_field_is_list(self):
        sgs, segs = plan_1_1()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        assert isinstance(result.trace.segments, list)

    def test_drift_field_is_list(self):
        sgs, segs = plan_1_1()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        assert isinstance(result.trace.drift, list)

    def test_repairs_field_is_list(self):
        sgs, segs = plan_1_1()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        assert isinstance(result.trace.repairs, list)

    def test_reflections_field_is_list(self):
        sgs, segs = plan_1_1()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        assert isinstance(result.trace.reflections, list)

    def test_memory_field_is_list(self):
        sgs, segs = plan_1_1()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        assert isinstance(result.trace.memory, list)

    def test_errors_field_is_list(self):
        sgs, segs = plan_1_1()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        assert isinstance(result.trace.errors, list)

    # ── JSON-safety ──────────────────────────────────────────────────────

    def test_full_trace_is_json_safe(self):
        """The entire trace dict must be JSON-safe."""
        sgs, segs = plan_2_3()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        assert is_json_safe(result.trace.to_dict())

    def test_trace_with_drift_is_json_safe(self):
        """Traces with drift entries must be JSON-safe."""
        sgs, segs = plan_with_drift()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        assert is_json_safe(result.trace.to_dict())

    # ── ordering ─────────────────────────────────────────────────────────

    def test_cycle_entries_are_ordered(self):
        """Cycle entries must be in increasing cycle order."""
        sgs, segs = plan_2_3()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        cycles = [c["cycle"] for c in result.trace.cycles]
        assert cycles == sorted(cycles)

    def test_memory_snapshots_are_ordered(self):
        """Memory snapshots must be in increasing cycle order."""
        sgs, segs = plan_2_3()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        mem_cycles = [m["cycle"] for m in result.trace.memory]
        assert mem_cycles == sorted(mem_cycles)

    # ── no nulls in required fields ──────────────────────────────────────

    def test_no_null_agent_entries(self):
        """Agent entries must not be None."""
        sgs, segs = plan_1_1()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        for entry in result.trace.agent:
            assert entry is not None
            assert "cycle" in entry

    def test_no_null_cycle_entries(self):
        """Cycle entries must not be None."""
        sgs, segs = plan_1_1()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        for entry in result.trace.cycles:
            assert entry is not None
            assert "cycle" in entry

    # ── memory snapshots present per cycle ───────────────────────────────

    def test_memory_snapshots_per_cycle(self):
        """There should be a memory snapshot for each cycle run."""
        sgs, segs = plan_2_3()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        assert len(result.trace.memory) == result.total_cycles

    # ── drift/repair/reflection cross-consistency ─────────────────────────

    def test_drift_and_repair_cycles_consistent(self):
        """Every repair cycle should have a corresponding drift entry."""
        sgs, segs = plan_with_drift()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        repair_cycles = {(r["cycle"], r["level"]) for r in result.trace.repairs}
        drift_cycles = {(d["cycle"], d["level"]) for d in result.trace.drift}
        # Every repair should have drift in the same cycle
        for rc in repair_cycles:
            assert rc in drift_cycles, (
                f"Repair at {rc} has no drift entry at same cycle"
            )
