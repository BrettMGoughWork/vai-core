"""
Phase 2.14.5 — E2E Helper Utilities

Pure, deterministic helpers for constructing minimal plans and running
the agent loop for smoke testing.  No I/O, no inference.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from src.core.planning.agent_loop.agent_loop_v3 import (
    AgentFullTrace,
    AgentLoopResult,
    run_agent_loop,
)
from src.core.types.plan_segment import PlanSegment
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState


# ──────────────────────────────────────────────────────────────────────────────
# Plan builders
# ──────────────────────────────────────────────────────────────────────────────


def build_minimal_plan(
    subgoal_count: int = 1,
    segments_per_subgoal: int = 1,
) -> Tuple[List[Subgoal], List[PlanSegment]]:
    """Construct a synthetic, deterministic plan of *subgoal_count* subgoals
    each with *segments_per_subgoal* segments.

    All steps are named ``sg.{i}.{j}.step{k}`` for easy trace inspection.
    """
    if subgoal_count < 1:
        raise ValueError("subgoal_count must be >= 1")
    if segments_per_subgoal < 1:
        raise ValueError("segments_per_subgoal must be >= 1")

    subgoals: List[Subgoal] = []
    segments: List[PlanSegment] = []

    for sg_i in range(1, subgoal_count + 1):
        sid = f"sg.{sg_i}"
        subgoals.append(
            Subgoal(
                subgoal_id=sid,
                goal=f"Complete task group {sg_i}",
                context={"index": sg_i},
                metadata={},
                state=SubgoalLifecycleState.ACTIVE,
            )
        )
        for seg_j in range(1, segments_per_subgoal + 1):
            segments.append(
                PlanSegment(
                    subgoal_id=sid,
                    steps=[
                        f"sg.{sg_i}.{seg_j}.step{k}"
                        for k in range(1, 3)
                    ],
                    context={"subgoal": sg_i, "segment": seg_j},
                    metadata={},
                )
            )

    return subgoals, segments


def plan_1_1() -> Tuple[List[Subgoal], List[PlanSegment]]:
    """1 subgoal, 1 segment — simplest happy path."""
    return build_minimal_plan(subgoal_count=1, segments_per_subgoal=1)


def plan_1_3() -> Tuple[List[Subgoal], List[PlanSegment]]:
    """1 subgoal, 3 segments — single-subgoal multi-segment."""
    return build_minimal_plan(subgoal_count=1, segments_per_subgoal=3)


def plan_2_2() -> Tuple[List[Subgoal], List[PlanSegment]]:
    """2 subgoals, 2 segments each — multi-subgoal."""
    return build_minimal_plan(subgoal_count=2, segments_per_subgoal=2)


# ──────────────────────────────────────────────────────────────────────────────
# Agent loop runner
# ──────────────────────────────────────────────────────────────────────────────


def run_agent_for_cycles(
    subgoals: List[Subgoal],
    segments: List[PlanSegment],
    max_cycles: int = 30,
) -> AgentLoopResult:
    """Run the agent loop on the given plan and return the result.

    Pure convenience wrapper — no assertions, just execution.
    """
    return run_agent_loop(subgoals=subgoals, segments=segments, max_cycles=max_cycles)


# ──────────────────────────────────────────────────────────────────────────────
# Trace utilities
# ──────────────────────────────────────────────────────────────────────────────


def extract_trace(result: AgentLoopResult) -> AgentFullTrace:
    """Extract the full trace from an AgentLoopResult."""
    return result.trace


def validate_trace_structure(trace: AgentFullTrace) -> List[str]:
    """Validate that the trace has all required top-level keys.

    Returns a list of missing keys (empty = valid).
    """
    required = [
        "cycles",
        "agent",
        "subgoals",
        "segments",
        "drift",
        "repairs",
        "reflections",
        "memory",
        "errors",
    ]
    td = trace.to_dict()
    return [k for k in required if k not in td]


def is_json_safe(obj: Any) -> bool:
    """Check whether *obj* round-trips through JSON serialisation."""
    try:
        json.dumps(obj)
        return True
    except (TypeError, OverflowError, ValueError):
        return False


def has_raw_strings(data: Any, _depth: int = 0) -> bool:
    """Recursively check for free-form strings in structured data.

    Returns True if **unexpected** raw strings are found (strings that are not
    values of expected string-type fields like 'type', 'message', 'goal', etc.).
    This is a heuristic — it flags very long strings (>200 chars) in dict values
    as likely free-form text.
    """
    if _depth > 20:
        return False  # safety valve

    if isinstance(data, str):
        # Strings longer than 200 chars in structured data are suspect
        return len(data) > 200
    if isinstance(data, dict):
        for val in data.values():
            if has_raw_strings(val, _depth + 1):
                return True
    if isinstance(data, (list, tuple)):
        for item in data:
            if has_raw_strings(item, _depth + 1):
                return True
    return False


def assert_no_raw_strings(trace: AgentFullTrace) -> None:
    """Assert that the trace contains no raw strings."""
    td = trace.to_dict()
    assert not has_raw_strings(td), (
        "Trace contains raw strings (free-form text > 200 chars)"
    )


def assert_errors_structured(errors: List[Dict[str, Any]]) -> None:
    """Assert that all error records are structured dicts with required keys."""
    for err in errors:
        assert isinstance(err, dict), f"Error is not a dict: {type(err)}"
        assert "error_type" in err or "type" in err, (
            f"Error missing type field: {err}"
        )
        assert "message" in err, f"Error missing message field: {err}"
