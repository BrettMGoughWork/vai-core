"""
Phase 2.13.4 — Golden Trace Tests
===================================

Capture deterministic trace output for a known plan and lock it in.
Future runs must produce byte-for-byte identical output (via JSON).
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.integration.agent.conftest import (
    is_json_safe,
    plan_1_1,
    plan_2_3,
    plan_with_drift,
    run_agent_loop,
    to_json,
)


# Directory for golden trace fixtures
_GOLDEN_DIR = Path(__file__).parent / "_golden"


def _save_golden(name: str, data: object) -> None:
    """Save a golden trace to disk for future comparison."""
    _GOLDEN_DIR.mkdir(exist_ok=True)
    path = _GOLDEN_DIR / f"{name}.json"
    path.write_text(json.dumps(data, sort_keys=True, indent=2, default=str))


def _load_golden(name: str) -> object:
    """Load a saved golden trace."""
    path = _GOLDEN_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


class TestAgentGoldenTraces:
    """Golden trace capture and validation."""

    # ── golden trace for 1-subgoal, 1-segment ───────────────────────────

    def test_golden_trace_1_1(self):
        """Golden trace for the simplest valid plan: 1 subgoal, 1 segment."""
        sgs, segs = plan_1_1()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
        trace_dict = result.trace.to_dict()

        existing = _load_golden("plan_1_1")
        if existing is None:
            _save_golden("plan_1_1", trace_dict)
        else:
            assert trace_dict == existing, (
                "Trace diverged from golden. Golden trace has changed."
            )

    # ── golden trace for 2-subgoal, 3-segment ───────────────────────────

    def test_golden_trace_2_3(self):
        """Golden trace for 2 subgoals, 3 segments."""
        sgs, segs = plan_2_3()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        trace_dict = result.trace.to_dict()

        existing = _load_golden("plan_2_3")
        if existing is None:
            _save_golden("plan_2_3", trace_dict)
        else:
            assert trace_dict == existing, (
                "Trace diverged from golden for plan_2_3"
            )

    # ── golden trace for plan with drift ─────────────────────────────────

    def test_golden_trace_with_drift(self):
        """Golden trace for a plan that triggers deterministic drift."""
        sgs, segs = plan_with_drift()
        result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=20)
        trace_dict = result.trace.to_dict()

        existing = _load_golden("plan_with_drift")
        if existing is None:
            _save_golden("plan_with_drift", trace_dict)
        else:
            assert trace_dict == existing, (
                "Trace diverged from golden for plan_with_drift"
            )

    # ── golden traces are JSON-safe ──────────────────────────────────────

    def test_golden_traces_are_json_safe(self):
        """All golden traces must be JSON-safe."""
        for name in ["plan_1_1", "plan_2_3", "plan_with_drift"]:
            existing = _load_golden(name)
            if existing is not None:
                assert is_json_safe(existing), (
                    f"Golden trace {name} is not JSON-safe"
                )

    # ── determinism across runs ──────────────────────────────────────────

    def test_golden_trace_deterministic(self):
        """Running the same plan 5 times always produces the golden trace."""
        sgs, segs = plan_1_1()
        golden = _load_golden("plan_1_1")
        if golden is None:
            # First run will create the golden
            result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
            _save_golden("plan_1_1", result.trace.to_dict())
            golden = _load_golden("plan_1_1")

        for _ in range(5):
            result = run_agent_loop(subgoals=sgs, segments=segs, max_cycles=10)
            assert result.trace.to_dict() == golden, (
                "Non-deterministic trace: run diverged from golden"
            )
