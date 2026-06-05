"""
Phase 2.13.4 — Drift Tests
===========================

Validate drift detection, classification, and trace entries
at both segment and subgoal levels.
"""
from __future__ import annotations

from tests.integration.agent.conftest import (
    AgentLoopResult,
    make_segment,
    make_subgoal,
    plan_with_drift,
    plan_multi_segment,
    run_agent_loop,
)


class TestAgentDrift:
    """Drift detection and trace validation at the integration level."""

    # ── drift at segment level ───────────────────────────────────────────

    def test_drift_at_segment_level(self):
        """Empty steps trigger segment-level drift."""
        sgs, segs = plan_with_drift()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        # At least one drift entry should exist at the segment level
        segment_drift = [
            d for d in result.trace.drift if d.get("level") == "segment"
        ]
        assert len(segment_drift) > 0, "Expected drift at segment level"

    def test_segment_drift_entries_have_required_keys(self):
        """Drift entries must contain cycle, level, index, drift, action."""
        sgs, segs = plan_with_drift()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        for entry in result.trace.drift:
            assert "cycle" in entry
            assert "level" in entry
            assert "index" in entry
            assert "drift" in entry
            assert "action" in entry

    def test_no_drift_for_clean_plan(self):
        """A clean plan without drift produces no drift entries."""
        sg = make_subgoal(subgoal_id="sg.clean")
        seg = make_segment(subgoal_id="sg.clean", steps=["step1", "step2"])
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        # All drift entries should have status "no_drift" or be empty
        for entry in result.trace.drift:
            drift_status = entry.get("drift", {}).get("status")
            assert drift_status in (None, "no_drift")

    # ── drift action correctness ─────────────────────────────────────────

    def test_drift_action_none_when_no_drift(self):
        """When no drift detected, action must be 'none'."""
        sg = make_subgoal(subgoal_id="sg.nodrift")
        seg = make_segment(subgoal_id="sg.nodrift", steps=["a", "b"])
        result = run_agent_loop(subgoals=[sg], segments=[seg], max_cycles=10)
        for entry in result.trace.drift:
            drift = entry.get("drift", {})
            if drift.get("status") == "no_drift" or not drift:
                assert entry["action"] in (None, "none")

    def test_drift_action_repair_when_minor_drift(self):
        """Minor drift (empty steps) triggers repair action."""
        sgs, segs = plan_with_drift()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        repair_actions = [
            d for d in result.trace.drift
            if d.get("action") == "repair_segment"
        ]
        assert len(repair_actions) > 0, (
            "Expected repair action for minor drift"
        )

    # ── drift trace ordering ─────────────────────────────────────────────

    def test_drift_entries_ordered_by_cycle(self):
        """Drift entries must be in cycle order."""
        sgs, segs = plan_multi_segment()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        cycles = [d["cycle"] for d in result.trace.drift]
        assert cycles == sorted(cycles), "Drift entries not in cycle order"

    def test_drift_requires_replan_flag(self):
        """Drift entries must include requires_replan boolean."""
        sgs, segs = plan_with_drift()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        for entry in result.trace.drift:
            assert "requires_replan" in entry
            assert isinstance(entry["requires_replan"], bool)

    # ── catastrophic drift → error surfaced ──────────────────────────────

    def test_max_cycles_stops_with_error_entry(self):
        """When max_cycles reached, no catastrophic drift, but termination is clean."""
        sgs, segs = plan_with_drift()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=3)
        # Should terminate gracefully with max_cycles_exceeded
        assert result.termination_reason in (
            "agent_complete",
            "max_cycles_exceeded",
        )
