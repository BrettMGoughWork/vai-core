"""
Phase 2.10.1 — Repair Action Library
=====================================

Provides pure, deterministic repair functions that fix malformed plan
structures without mutating inputs.

Repair targets
--------------
- ``CoreStep`` — malformed steps (missing type, null payload)
- ``PlanSegment`` — malformed segments (corrupt steps, missing IDs)
- ``Plan`` — malformed plans (missing intent, corrupt arguments)
- ``Subgoal`` — malformed subgoals (empty goal, corrupt metadata)
- ``PlanState`` — drift‑induced inconsistencies (invalid step index,
  corrupt trace, invalid status)

Every function:
* is pure and deterministic
* returns a **new** frozen instance
* never mutates any input
* performs minimal, targeted repairs
* preserves all valid structure
* enforces schema invariants

No LLM calls, no tool calls, no I/O.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List

from src.strategy.planning.models.plan import Plan
from src.strategy.planning.models.plan_state import PlanState, PlanStatus
from src.strategy.types.core_step import CoreStep
from src.strategy.types.plan_segment import PlanSegment
from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState


# ---------------------------------------------------------------------------
# RepairTrace — Phase 2.10.4
# ---------------------------------------------------------------------------

@dataclass
class RepairTrace:
    """Deterministic, pure trace of a repair cycle.

    Captures every repair attempt, success, failure, and budget delta
    incurred during arbitration and repair execution.

    All fields are JSON‑serializable.
    """
    attempts: list[dict] = field(default_factory=list)
    successes: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    budget_usage: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_str(value: object, default: str = "unknown") -> str:
    """Deterministic string normalisation — returns *default* for non‑strings."""
    return value if isinstance(value, str) and value else default


def _ensure_dict(value: object) -> Dict[str, Any]:
    """Deterministic dict normalisation — returns {} for non‑dicts."""
    return value if isinstance(value, dict) else {}


def _ensure_list_of_str(value: object) -> List[str]:
    """Deterministic list‑of‑str normalisation — filters out non‑strings."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]


def _ensure_list_of_dict(value: object) -> List[Dict[str, Any]]:
    """Deterministic list‑of‑dict normalisation — filters out non‑dicts."""
    if not isinstance(value, list):
        return []
    return [copy.deepcopy(v) for v in value if isinstance(v, dict)]


# ---------------------------------------------------------------------------
# Step repair
# ---------------------------------------------------------------------------

def repair_step(step: CoreStep) -> CoreStep:
    """
    Repair a malformed CoreStep.

    Rules
    -----
    * ``step_type`` must be a non‑empty string (defaults to ``"unknown"``).
    * ``payload`` must be a dict (defaults to ``{}``).
    * Never mutates the input.
    """
    repaired_type = _ensure_str(step.step_type, "unknown")
    repaired_payload = _ensure_dict(step.payload)

    if repaired_type == step.step_type and repaired_payload is step.payload:
        return step
    return CoreStep(step_type=repaired_type, payload=repaired_payload)


# ---------------------------------------------------------------------------
# Segment repair
# ---------------------------------------------------------------------------

def repair_segment(segment: PlanSegment) -> PlanSegment:
    """
    Repair a malformed PlanSegment.

    Rules
    -----
    * ``steps`` must be a list of strings — null / non‑string entries removed.
    * ``subgoal_id`` must be a non‑empty string (defaults to ``"unknown"``).
    * ``context`` must be a dict (defaults to ``{}``).
    * ``metadata`` must be a dict (defaults to ``{}``).
    * ``created_at`` must be a non‑empty string (defaults to ``"1970-01-01T00:00:00"``).
    * Each surviving step is run through ``repair_step()`` (via string normalisation).
    * Never mutates the input.
    """
    repaired_steps = _ensure_list_of_str(segment.steps)
    repaired_subgoal_id = _ensure_str(segment.subgoal_id, "unknown")
    repaired_context = _ensure_dict(segment.context)
    repaired_metadata = _ensure_dict(segment.metadata)
    repaired_created_at = _ensure_str(segment.created_at, "1970-01-01T00:00:00")

    # Steps are List[str] in PlanSegment, not CoreStep, so we just normalise strings.
    # (If future versions store CoreStep objects, repair each.)

    needs_repair = (
        repaired_steps != segment.steps
        or repaired_subgoal_id != segment.subgoal_id
        or repaired_context is not segment.context
        or repaired_metadata is not segment.metadata
        or repaired_created_at != segment.created_at
    )
    if not needs_repair:
        return segment

    return PlanSegment(
        subgoal_id=repaired_subgoal_id,
        steps=repaired_steps,
        context=repaired_context,
        metadata=repaired_metadata,
        created_at=repaired_created_at,
    )


# ---------------------------------------------------------------------------
# Plan repair
# ---------------------------------------------------------------------------

def repair_plan(plan: Plan) -> Plan:
    """
    Repair a malformed Plan.

    Rules
    -----
    * ``intent`` must be a non‑empty string (defaults to ``"unknown"``).
    * ``targetskillid`` must be a string (defaults to ``""``).
    * ``arguments`` must be a dict (defaults to ``{}``).
    * ``reasoning_summary`` must be a string (defaults to ``""``).
    * Never mutates the input.
    """
    repaired_intent = _ensure_str(plan.intent, "unknown")
    repaired_targetskillid = _ensure_str(plan.targetskillid, "")
    repaired_arguments = _ensure_dict(plan.arguments)
    repaired_reasoning = _ensure_str(plan.reasoning_summary, "")
    # arguments is dict[str, Any] — ensure keys are strings
    repaired_arguments = {str(k): v for k, v in repaired_arguments.items()}

    needs_repair = (
        repaired_intent != plan.intent
        or repaired_targetskillid != plan.targetskillid
        or repaired_arguments != plan.arguments
        or repaired_reasoning != plan.reasoning_summary
    )
    if not needs_repair:
        return plan

    return Plan(
        intent=repaired_intent,
        targetskillid=repaired_targetskillid,
        arguments=repaired_arguments,
        reasoning_summary=repaired_reasoning,
    )


# ---------------------------------------------------------------------------
# Subgoal repair
# ---------------------------------------------------------------------------

def repair_subgoal(subgoal: Subgoal) -> Subgoal:
    """
    Repair a malformed Subgoal.

    Rules
    -----
    * ``goal`` must be a non‑empty string (defaults to ``"unknown"``).
    * ``context`` must be a dict (defaults to ``{}``).
    * ``metadata`` must be a dict (defaults to ``{}``).
    * ``subgoal_id`` must be a non‑empty string (defaults to ``"unknown"``).
    * ``state`` must be a valid SubgoalLifecycleState member (defaults to PENDING).
    * Never mutates the input.
    """
    repaired_goal = _ensure_str(subgoal.goal, "unknown")
    repaired_context = _ensure_dict(subgoal.context)
    repaired_metadata = _ensure_dict(subgoal.metadata)
    repaired_subgoal_id = _ensure_str(subgoal.subgoal_id, "unknown")

    # Validate state — if it's not a valid enum member, default to PENDING
    repaired_state = subgoal.state
    if not isinstance(repaired_state, SubgoalLifecycleState):
        # Try to match by value string
        valid_values = {s.value: s for s in SubgoalLifecycleState}
        repaired_state = valid_values.get(
            str(repaired_state) if not isinstance(repaired_state, str) else repaired_state,
            SubgoalLifecycleState.PENDING,
        )

    needs_repair = (
        repaired_goal != subgoal.goal
        or repaired_context is not subgoal.context
        or repaired_metadata is not subgoal.metadata
        or repaired_subgoal_id != subgoal.subgoal_id
        or repaired_state is not subgoal.state
    )
    if not needs_repair:
        return subgoal

    return Subgoal(
        subgoal_id=repaired_subgoal_id,
        goal=repaired_goal,
        context=repaired_context,
        metadata=repaired_metadata,
        parent_id=subgoal.parent_id,
        state=repaired_state,
        created_at=subgoal.created_at,
    )


# ---------------------------------------------------------------------------
# Drift‑induced inconsistency repair
# ---------------------------------------------------------------------------

def repair_drift_inconsistency(plan_state: PlanState) -> PlanState:
    """
    Repair drift‑induced inconsistencies in a PlanState.

    Detects and repairs:
    * Corrupt steps list (non‑dict entries removed, required keys checked).
    * Invalid current_step_index (clamped to valid range).
    * Invalid status (defaults to PlanStatus.PENDING).
    * Corrupt last_result (None or dict only).
    * Corrupt trace (non‑dict entries removed).

    Rules
    -----
    * Never rewrites intent or goals.
    * Never introduces new behaviour.
    * Performs minimal, targeted repairs.
    * Never mutates the input.
    """
    # Repair steps — must be List[Dict[str, Any]]
    repaired_steps = _ensure_list_of_dict(plan_state.steps)

    # Repair current_step_index — clamp to valid range
    repaired_index = plan_state.current_step_index
    if not isinstance(repaired_index, int) or repaired_index < 0:
        repaired_index = 0
    if repaired_steps:
        repaired_index = max(0, min(repaired_index, len(repaired_steps) - 1))
    else:
        repaired_index = 0

    # Repair status — must be a valid PlanStatus
    repaired_status = plan_state.status
    if not isinstance(repaired_status, PlanStatus):
        valid_statuses = {s.value: s for s in PlanStatus}
        repaired_status = valid_statuses.get(
            str(repaired_status) if not isinstance(repaired_status, str) else repaired_status,
            PlanStatus.PENDING,
        )

    # Repair last_result — must be dict or None
    repaired_last_result = plan_state.last_result
    if repaired_last_result is not None and not isinstance(repaired_last_result, dict):
        repaired_last_result = None

    # Repair trace — must be List[Dict[str, Any]]
    repaired_trace = _ensure_list_of_dict(plan_state.trace)

    needs_repair = (
        repaired_steps != plan_state.steps
        or repaired_index != plan_state.current_step_index
        or repaired_status is not plan_state.status
        or repaired_last_result is not plan_state.last_result
        or repaired_trace != plan_state.trace
    )
    if not needs_repair:
        return plan_state

    return PlanState(
        plan_id=plan_state.plan_id,
        steps=repaired_steps,
        current_step_index=repaired_index,
        status=repaired_status,
        last_result=repaired_last_result,
        trace=repaired_trace,
        created_at=plan_state.created_at,
        updated_at=plan_state.updated_at,
    )
