"""
Shared helpers for the Release 1 agent integration test suite.

No fixtures requiring I/O — all helpers are pure, deterministic, and JSON-safe.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from src.strategy.planning.agent_loop.agent_loop import (
    AgentFullTrace,
    AgentLoopResult,
    run_agent_loop,
)
from src.strategy.types.plan_segment import PlanSegment
from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState


# ──────────────────────────────────────────────────────────────────────────────
# Test plan builders
# ──────────────────────────────────────────────────────────────────────────────


def make_subgoal(
    subgoal_id: str = "sg.test",
    goal: str = "Test goal",
    context: dict | None = None,
    metadata: dict | None = None,
) -> Subgoal:
    """Create a minimal valid Subgoal for testing."""
    return Subgoal(
        subgoal_id=subgoal_id,
        goal=goal,
        context=context if context is not None else {"key": "value"},
        metadata=metadata if metadata is not None else {},
        state=SubgoalLifecycleState.ACTIVE,
    )


def make_segment(
    subgoal_id: str = "sg.test",
    steps: list | None = None,
    context: dict | None = None,
) -> PlanSegment:
    """Create a minimal valid PlanSegment for testing.

    NOTE: PlanSegment computes segment_id automatically via stable_hash.
    """
    return PlanSegment(
        subgoal_id=subgoal_id,
        steps=steps if steps is not None else ["noop"],
        context=context if context is not None else {},
        metadata={},
    )


def is_json_safe(obj: object) -> bool:
    """Check that an object is JSON-serialisable."""
    try:
        json.dumps(obj)
        return True
    except (TypeError, OverflowError):
        return False


def to_json(obj: object) -> str:
    """Serialize an object to JSON with sorted keys."""
    return json.dumps(obj, sort_keys=True, default=str)


def trace_keys(trace: AgentFullTrace) -> List[str]:
    """Return the ordered list of required keys in an AgentFullTrace."""
    return sorted([
        "cycles",
        "agent",
        "subgoals",
        "segments",
        "drift",
        "repairs",
        "reflections",
        "memory",
        "errors",
    ])


# ──────────────────────────────────────────────────────────────────────────────
# Plan factories for common scenarios
# ──────────────────────────────────────────────────────────────────────────────


def plan_1_1() -> tuple[List[Subgoal], List[PlanSegment]]:
    """Return a 1-subgoal, 1-segment plan with no drift."""
    sg = make_subgoal(subgoal_id="sg.1", goal="Complete task A")
    seg = make_segment(subgoal_id="sg.1", steps=["step.a1", "step.a2"])
    return [sg], [seg]


def plan_2_3() -> tuple[List[Subgoal], List[PlanSegment]]:
    """Return a 2-subgoal, 3-segment plan (2+1 segments across subgoals)."""
    sg1 = make_subgoal(subgoal_id="sg.1", goal="First subgoal")
    sg2 = make_subgoal(subgoal_id="sg.2", goal="Second subgoal")
    seg1a = make_segment(subgoal_id="sg.1", steps=["s1.a"])
    seg1b = make_segment(subgoal_id="sg.1", steps=["s1.b"])
    seg2a = make_segment(subgoal_id="sg.2", steps=["s2.a"])
    return [sg1, sg2], [seg1a, seg1b, seg2a]


def plan_3_6() -> tuple[List[Subgoal], List[PlanSegment]]:
    """Return a 3-subgoal plan with 2 segments each (6 total)."""
    sgs = [
        make_subgoal(subgoal_id="sg.1", goal="Subgoal 1"),
        make_subgoal(subgoal_id="sg.2", goal="Subgoal 2"),
        make_subgoal(subgoal_id="sg.3", goal="Subgoal 3"),
    ]
    segs = []
    for sgi in range(1, 4):
        for segj in range(1, 3):
            segs.append(make_segment(
                subgoal_id=f"sg.{sgi}",
                steps=[f"s{sgi}.{segj}.a", f"s{sgi}.{segj}.b"],
            ))
    return sgs, segs


def plan_with_drift() -> tuple[List[Subgoal], List[PlanSegment]]:
    """Return a plan with segments that trigger deterministic drift.

    - seg.1: empty steps → "empty_steps" signal (minor drift)
    - seg.2: missing subgoal_id → "missing_field" signal (minor drift)
    """
    sg = make_subgoal(subgoal_id="sg.drift", goal="Drift test")
    seg1 = make_segment(subgoal_id="sg.drift", steps=[])  # empty steps = drift
    seg2 = make_segment(subgoal_id="sg.drift", steps=["valid"])
    # Set subgoal_id to empty to trigger missing_field drift
    seg2 = PlanSegment(
        subgoal_id="",
        steps=["valid"],
        context={},
        metadata={},
    )
    return [sg], [seg1, seg2]


def plan_multi_segment() -> tuple[List[Subgoal], List[PlanSegment]]:
    """1 subgoal, 3 segments with mixed drift."""
    sg = make_subgoal(subgoal_id="sg.multi", goal="Multi-segment test")
    seg1 = make_segment(subgoal_id="sg.multi", steps=[])  # drift: empty steps
    seg2 = make_segment(subgoal_id="sg.multi", steps=["mid.a", "mid.b"])  # clean
    seg3 = make_segment(subgoal_id="sg.multi", steps=["end.a"])  # clean
    return [sg], [seg1, seg2, seg3]
