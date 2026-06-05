"""
Phase 2.12.4 — Subgoal Trace
=============================

Deterministic, pure‑function trace for subgoal‑level execution cycles.
Captures transitions, drift, repair, and reflection entries in a single
``SubgoalTrace`` structure.

The main entry point is ``execute_subgoal_cycle``, which runs the full
pipeline (reflect → drift → repair → transition) and produces a trace.

Constraints
-----------
- Pure functions only — no side effects, no mutation of inputs.
- No I/O, no inference, no LLM calls.
- Deterministic — identical inputs always produce identical outputs.
- JSON‑safe — all output structures are serialisable to JSON.
- Reuses existing drift (2.12.3), reflection (2.12.2), and execution (2.12.1)
  substrate without modification.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

from src.core.types.subgoal import Subgoal

from .drift import (
    SubgoalDriftResult,
    apply_subgoal_repair,
    evaluate_subgoal_drift,
)
from .execution import (
    SubgoalExecutionState,
    update_subgoal_execution_state,
)
from .reflection import (
    SubgoalReflectionResult,
    reflect_on_subgoal,
)


# ──────────────────────────────────────────────────────────────────────────────
# SubgoalTrace
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SubgoalTrace:
    """Deterministic trace of a single subgoal‑execution cycle.

    Fields
    ------
    transitions
        State transition records: ``from_state``, ``to_state``,
        ``index_before``, ``index_after``.
    drift
        Drift evaluation records: ``drift``, ``action``, ``requires_replan``.
    repairs
        Repair action records: ``action`` and (if applicable) ``repaired_subgoal``.
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


def build_subgoal_trace(
    exec_state: SubgoalExecutionState,
    subgoal: Subgoal,
    reflection: SubgoalReflectionResult,
    drift_result: SubgoalDriftResult,
    new_exec_state: SubgoalExecutionState,
) -> SubgoalTrace:
    """Build a SubgoalTrace from a single execution cycle's data.

    Aggregates transitions, drift signals, repair actions, and reflection
    summaries into one deterministic trace.  Does not mutate any input.

    Returns
    -------
    SubgoalTrace
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
    if drift_result.action == "repair_subgoal":
        repairs.append(
            {
                "action": "repair_subgoal",
                "repaired_subgoal": drift_result.repaired_subgoal,
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

    return SubgoalTrace(
        transitions=transitions,
        drift=drift,
        repairs=repairs,
        reflections=reflections,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Subgoal execution cycle orchestrator
# ──────────────────────────────────────────────────────────────────────────────


def execute_subgoal_cycle(
    exec_state: SubgoalExecutionState,
    subgoal: Subgoal,
    total_subgoals: int,
) -> Dict[str, Any]:
    """Run one full subgoal‑execution cycle with trace.

    Pipeline order (deterministic):
    1. reflect_on_subgoal — full reflection
    2. evaluate_subgoal_drift — drift classification + action
    3. apply_subgoal_repair — repair if needed
    4. update_subgoal_execution_state — state transition
    5. build_subgoal_trace — aggregate trace entries

    Returns
    -------
    dict
        ``execution_state`` — new ``SubgoalExecutionState`` after transition.
        ``subgoal`` — repaired (or original) subgoal as a JSON‑safe dict.
        ``subgoal_trace`` — ``SubgoalTrace`` dataclass with all trace entries.
    """
    # 1. Reflect
    reflection = reflect_on_subgoal(subgoal)

    # 2. Drift
    drift_result = evaluate_subgoal_drift(subgoal)

    # 3. Repair / resolve subgoal
    if drift_result.action == "repair_subgoal":
        repaired_subgoal = apply_subgoal_repair(subgoal, drift_result.drift)
    else:
        repaired_subgoal = drift_result.repaired_subgoal  # already JSON‑safe

    # 4. Transition
    new_exec_state = update_subgoal_execution_state(
        exec_state, reflection.is_complete, total_subgoals
    )

    # 5. Trace
    trace = build_subgoal_trace(
        exec_state, subgoal, reflection, drift_result, new_exec_state
    )

    return {
        "execution_state": new_exec_state,
        "subgoal": repaired_subgoal,
        "subgoal_trace": trace,
    }
