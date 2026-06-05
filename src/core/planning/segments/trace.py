"""
Phase 2.11.4 — Segment Trace
=============================

Deterministic, pure‑function trace for segment‑level execution cycles.
Captures transitions, drift, repair, and reflection entries in a single
``SegmentTrace`` structure.

The main entry point is ``execute_segment_cycle``, which runs the full
pipeline (reflect → drift → repair → transition) and produces a trace.

Constraints
-----------
- Pure functions only — no side effects, no mutation of inputs.
- No I/O, no inference, no LLM calls.
- Deterministic — identical inputs always produce identical outputs.
- JSON‑safe — all output structures are serialisable to JSON.
- Reuses existing drift (2.11.3), reflection (2.11.2), and execution (2.11.1)
  substrate without modification.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

from src.core.types.plan_segment import PlanSegment

from .drift import (
    SegmentDriftResult,
    apply_segment_repair,
    evaluate_segment_drift,
)
from .execution import (
    SegmentExecutionState,
    update_segment_execution_state,
)
from .reflection import (
    SegmentReflectionResult,
    evaluate_segment_completion,
    reflect_on_segment,
)


# ──────────────────────────────────────────────────────────────────────────────
# SegmentTrace
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SegmentTrace:
    """Deterministic trace of a single segment‑execution cycle.

    Fields
    ------
    transitions
        State transition records: ``from_state``, ``to_state``,
        ``index_before``, ``index_after``.
    drift
        Drift evaluation records: ``drift``, ``action``, ``requires_replan``.
    repairs
        Repair action records: ``action`` and (if applicable) ``repaired_segment``.
    reflections
        Reflection summaries: ``progress``, ``drift``, ``repair``, ``is_complete``.
    """

    transitions: List[Dict[str, Any]]
    drift: List[Dict[str, Any]]
    repairs: List[Dict[str, Any]]
    reflections: List[Dict[str, Any]]

    def __hash__(self) -> int:
        """Deterministic hash via JSON‑stable serialisation."""
        return hash(
            (
                json.dumps(self.transitions, sort_keys=True),
                json.dumps(self.drift, sort_keys=True),
                json.dumps(self.repairs, sort_keys=True),
                json.dumps(self.reflections, sort_keys=True),
            )
        )


# ──────────────────────────────────────────────────────────────────────────────
# Pure trace-building function
# ──────────────────────────────────────────────────────────────────────────────


def build_segment_trace(
    exec_state: SegmentExecutionState,
    segment: PlanSegment,
    reflection: SegmentReflectionResult,
    drift_result: SegmentDriftResult,
    new_exec_state: SegmentExecutionState,
) -> SegmentTrace:
    """Build a SegmentTrace from a single execution cycle's data.

    Aggregates transitions, drift signals, repair actions, and reflection
    summaries into one deterministic trace.  Does not mutate any input.

    Returns
    -------
    SegmentTrace
        Complete trace for the cycle.
    """
    # ── transitions ──
    transitions: List[Dict[str, Any]] = [
        {
            "from_state": exec_state.state,
            "to_state": new_exec_state.state,
            "index_before": exec_state.index,
            "index_after": new_exec_state.index,
        }
    ]

    # ── drift ──
    drift: List[Dict[str, Any]] = [
        {
            "drift": drift_result.drift,
            "action": drift_result.action,
            "requires_replan": drift_result.requires_replan,
        }
    ]

    # ── repairs ──
    repairs: List[Dict[str, Any]] = []
    if drift_result.action == "repair_segment":
        repairs.append(
            {
                "action": "repair_segment",
                "repaired_segment": drift_result.repaired_segment,
            }
        )
    else:
        repairs.append({"action": drift_result.action})

    # ── reflections ──
    reflections: List[Dict[str, Any]] = [
        {
            "progress": reflection.progress,
            "drift": reflection.drift,
            "repair": reflection.repair,
            "is_complete": reflection.is_complete,
        }
    ]

    return SegmentTrace(
        transitions=transitions,
        drift=drift,
        repairs=repairs,
        reflections=reflections,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Segment execution cycle orchestrator
# ──────────────────────────────────────────────────────────────────────────────


def execute_segment_cycle(
    exec_state: SegmentExecutionState,
    segment: PlanSegment,
    total_segments: int,
) -> Dict[str, Any]:
    """Run one full segment‑execution cycle with trace.

    Pipeline order (deterministic):
    1. reflect_on_segment — full reflection
    2. evaluate_segment_drift — drift classification + action
    3. apply_segment_repair — repair if needed
    4. update_segment_execution_state — state transition
    5. build_segment_trace — aggregate trace entries

    Returns
    -------
    dict
        ``execution_state`` — new ``SegmentExecutionState`` after transition.
        ``segment`` — repaired (or original) segment as a JSON‑safe dict.
        ``segment_trace`` — ``SegmentTrace`` dataclass with all trace entries.
    """
    # 1. Reflect
    reflection = reflect_on_segment(segment)

    # 2. Drift
    drift_result = evaluate_segment_drift(segment)

    # 3. Repair / resolve segment
    if drift_result.action == "repair_segment":
        repaired_segment = apply_segment_repair(segment, drift_result.drift)
    else:
        repaired_segment = drift_result.repaired_segment  # already JSON‑safe

    # 4. Transition
    new_exec_state = update_segment_execution_state(
        exec_state, reflection.is_complete, total_segments
    )

    # 5. Trace
    trace = build_segment_trace(
        exec_state, segment, reflection, drift_result, new_exec_state
    )

    return {
        "execution_state": new_exec_state,
        "segment": repaired_segment,
        "segment_trace": trace,
    }
