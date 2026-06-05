"""
Phase 2.13.4 — Repair Tests
============================

Validate repair detection, application, and trace entries
at both segment and subgoal levels.
"""
from __future__ import annotations

from tests.integration.agent.conftest import (
    is_json_safe,
    make_segment,
    make_subgoal,
    plan_with_drift,
    plan_multi_segment,
    run_agent_loop,
)


class TestAgentRepair:
    """Repair application and trace validation at the integration level."""

    # ── repair at segment level ──────────────────────────────────────────

    def test_repair_for_empty_steps(self):
        """Empty steps should trigger repair."""
        sgs, segs = plan_with_drift()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        segment_repairs = [
            r for r in result.trace.repairs
            if r.get("level") == "segment"
        ]
        assert len(segment_repairs) > 0, "Expected repair at segment level"

    def test_repair_entries_have_required_keys(self):
        """Repair entries must contain cycle, level, action."""
        sgs, segs = plan_with_drift()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        for entry in result.trace.repairs:
            assert "cycle" in entry
            assert "level" in entry
            assert "action" in entry

    def test_no_repair_for_clean_plan(self):
        """A clean plan with no drift produces no repair actions."""
        sg = make_subgoal(subgoal_id="sg.clean")
        seg = make_segment(subgoal_id="sg.clean", steps=["s1", "s2", "s3"])
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        repair_actions = [
            r for r in result.trace.repairs
            if r.get("action") not in (None, "none")
        ]
        assert len(repair_actions) == 0, (
            "Expected no repair actions for clean plan"
        )

    # ── repaired plan remains JSON-safe ──────────────────────────────────

    def test_repaired_segment_json_safe(self):
        """Repaired segment entries must be JSON-safe."""
        sgs, segs = plan_with_drift()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        for entry in result.trace.repairs:
            assert is_json_safe(entry), f"Repair entry not JSON-safe: {entry}"

    def test_full_trace_json_safe(self):
        """The full trace must remain JSON-safe after repairs."""
        sgs, segs = plan_with_drift()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        assert is_json_safe(result.trace.to_dict()), "Full trace not JSON-safe"

    # ── repaired plan produces deterministic output ──────────────────────

    def test_repaired_output_is_deterministic(self):
        """Running the same drifted plan twice produces identical repair output."""
        sgs, segs = plan_with_drift()
        r1 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        r2 = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        assert r1.trace.repairs == r2.trace.repairs

    # ── repair trace ordering ────────────────────────────────────────────

    def test_repair_entries_ordered_by_cycle(self):
        """Repair entries must be in cycle order."""
        sgs, segs = plan_multi_segment()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        cycles = [r["cycle"] for r in result.trace.repairs]
        assert cycles == sorted(cycles), "Repair entries not in cycle order"

    # ── malformed steps → repaired ──────────────────────────────────────

    def test_missing_fields_repaired(self):
        """Empty steps (missing field) should be repaired."""
        sg = make_subgoal(subgoal_id="sg.repair")
        # empty steps = missing field → drift → repair
        seg = make_segment(subgoal_id="sg.repair", steps=[])
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        # Repair should have been attempted
        repair_actions = [
            r for r in result.trace.repairs
            if r.get("action") not in (None, "none")
        ]
        assert len(repair_actions) > 0, (
            "Expected repair action for empty steps"
        )
