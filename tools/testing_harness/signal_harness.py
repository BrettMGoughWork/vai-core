"""
Phase 2.10.x — Stratum‑2 Signal Harness
===========================================

Deterministic, stdin‑driven CLI tool for end‑to‑end validation of the
full drift‑to‑repair pipeline before moving to Stratum‑3.

Reads JSON from stdin, runs the pipeline:

     signals → classification → arbitration → action → budget update

and prints a complete state‑transition trace.

Pure, deterministic, JSON‑safe — never calls an LLM, never mutates
inputs, never performs I/O beyond stdin/stdout.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Union

from src.core.planning.drift.unified_drift_types import (
    UnifiedDriftClassification,
    UnifiedDriftSignal,
)
from src.core.planning.drift.unified_drift_classifier import classify_unified_drift
from src.core.planning.drift.repair_budget import (
    RepairBudgetConfig,
    RepairBudgetState,
    apply_repair_budget,
    is_budget_exhausted,
)
from src.core.planning.drift.repair_arbitration import (
    ArbitrationDecision,
    decide_arbitration_action,
)
from src.core.planning.drift.repair_action_library import (
    repair_drift_inconsistency,
    repair_plan,
    repair_segment,
    repair_subgoal,
)
from src.core.planning.models.plan import Plan
from src.core.planning.models.plan_state import PlanState, PlanStatus
from src.core.types.plan_segment import PlanSegment
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState


# ──────────────────────────────────────────────────────────────────────────────
# JSON serialisation helpers
# ──────────────────────────────────────────────────────────────────────────────

def _to_json_safe(obj: Any) -> Any:
    """Recursively convert dataclasses, enums, and lists to JSON‑safe dicts."""
    if hasattr(obj, "__dataclass_fields__"):
        result: Dict[str, Any] = {}
        for f_name in obj.__dataclass_fields__:
            value = getattr(obj, f_name)
            result[f_name] = _to_json_safe(value)
        return result
    if hasattr(obj, "value"):
        # Enum
        return obj.value
    if isinstance(obj, list):
        return [_to_json_safe(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): _to_json_safe(v) for k, v in obj.items()}
    return obj


def _print_section(title: str, payload: Any) -> None:
    """Print a section header followed by JSON‑safe payload."""
    sys.stdout.write(f"=== {title} ===\n")
    json.dump(_to_json_safe(payload), sys.stdout, indent=2, default=str)
    sys.stdout.write("\n\n")


def _fatal(message: str, exit_code: int = 1) -> None:
    """Print an error section and exit."""
    sys.stdout.write("=== ERROR ===\n")
    sys.stdout.write(f"{message}\n")
    sys.exit(exit_code)


# ──────────────────────────────────────────────────────────────────────────────
# Input constructors — build typed objects from JSON‑safe dicts
# ──────────────────────────────────────────────────────────────────────────────

def _build_signals(raw: List[Dict[str, Any]]) -> List[UnifiedDriftSignal]:
    """Convert a list of signal dicts into ``UnifiedDriftSignal`` instances."""
    signals: List[UnifiedDriftSignal] = []
    for entry in raw:
        try:
            signals.append(UnifiedDriftSignal(
                source=entry["source"],
                type=entry["type"],
                weight=float(entry["weight"]),
                decay=float(entry.get("decay", 1.0)),
                confidence=float(entry.get("confidence", 0.5)),
                details=entry.get("details", {}),
            ))
        except (KeyError, ValueError, TypeError) as exc:
            _fatal(f"Invalid signal entry: {entry!r} — {exc}")
    return signals


def _build_classification(
    raw: Optional[Dict[str, Any]],
) -> Optional[UnifiedDriftClassification]:
    """Reconstruct a previous ``UnifiedDriftClassification`` from a dict."""
    if raw is None:
        return None
    try:
        reasons = _build_signals(raw.get("reasons", []))
        return UnifiedDriftClassification(
            status=raw["status"],
            severity=raw["severity"],
            categories=list(raw.get("categories", [])),
            confidence=float(raw["confidence"]),
            reasons=reasons,
            streak=int(raw.get("streak", 0)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        _fatal(f"Invalid previous_classification: {raw!r} — {exc}")


def _build_budget_config(raw: Optional[Dict[str, Any]]) -> RepairBudgetConfig:
    """Build a ``RepairBudgetConfig`` from a dict, or return defaults."""
    if raw is None:
        return RepairBudgetConfig()
    try:
        return RepairBudgetConfig(
            max_cycle=int(raw.get("max_cycle", 5)),
            max_subgoal=int(raw.get("max_subgoal", 10)),
            max_plan=int(raw.get("max_plan", 20)),
            max_global=int(raw.get("max_global", 50)),
        )
    except (ValueError, TypeError) as exc:
        _fatal(f"Invalid budget_config: {raw!r} — {exc}")


def _build_budget_state(
    config: RepairBudgetConfig,
    raw: Optional[Dict[str, Any]],
) -> RepairBudgetState:
    """Build a ``RepairBudgetState`` from a dict, or return fresh state."""
    if raw is None:
        return RepairBudgetState(config=config)
    try:
        return RepairBudgetState(
            usage_cycle=int(raw.get("usage_cycle", 0)),
            usage_subgoal=int(raw.get("usage_subgoal", 0)),
            usage_plan=int(raw.get("usage_plan", 0)),
            usage_global=int(raw.get("usage_global", 0)),
            config=config,
        )
    except (ValueError, TypeError) as exc:
        _fatal(f"Invalid budget_usage: {raw!r} — {exc}")


def _build_plan_state(raw: Optional[Dict[str, Any]]) -> PlanState:
    """Build a ``PlanState`` from a dict, or return a minimal default."""
    if raw is None:
        return PlanState(
            plan_id="harness-default-plan",
            steps=[],
            current_step_index=0,
            status=PlanStatus.PENDING,
            last_result=None,
            trace=[],
            created_at=0,
            updated_at=0,
        )

    status_raw = raw.get("status", "pending")
    if isinstance(status_raw, str):
        status_val = PlanStatus(status_raw)
    else:
        status_val = PlanStatus("pending")

    return PlanState(
        plan_id=str(raw.get("plan_id", "harness-default-plan")),
        steps=list(raw.get("steps", [])),
        current_step_index=int(raw.get("current_step_index", 0)),
        status=status_val,
        last_result=raw.get("last_result"),
        trace=list(raw.get("trace", [])),
        created_at=int(raw.get("created_at", 0)),
        updated_at=int(raw.get("updated_at", 0)),
    )


def _build_plan(raw: Optional[Dict[str, Any]]) -> Plan:
    """Build a ``Plan`` from a dict, or return a deterministic placeholder."""
    if raw is None:
        return Plan(
            intent="placeholder_intent",
            targetskillid="placeholder_skill",
            arguments={},
            reasoning_summary="",
        )
    return Plan(
        intent=str(raw.get("intent", "placeholder_intent")),
        targetskillid=str(raw.get("targetskillid", "")),
        arguments=dict(raw.get("arguments", {})),
        reasoning_summary=str(raw.get("reasoning_summary", "")),
    )


def _build_segment(raw: Optional[Dict[str, Any]]) -> PlanSegment:
    """Build a ``PlanSegment`` from a dict, or return a deterministic placeholder."""
    if raw is None:
        return PlanSegment(
            subgoal_id="placeholder_segment",
            steps=[],
        )
    return PlanSegment(
        subgoal_id=str(raw.get("subgoal_id", "placeholder_segment")),
        steps=list(raw.get("steps", [])),
        context=dict(raw.get("context", {})),
        metadata=dict(raw.get("metadata", {})),
        created_at=str(raw.get("created_at", "1970-01-01T00:00:00")),
    )


def _build_subgoal(raw: Optional[Dict[str, Any]]) -> Subgoal:
    """Build a ``Subgoal`` from a dict, or return a deterministic placeholder."""
    if raw is None:
        return Subgoal(
            subgoal_id="placeholder_subgoal",
            goal="placeholder_goal",
            context={},
            metadata={},
        )
    state_raw = raw.get("state", "pending")
    if isinstance(state_raw, str):
        state_val = SubgoalLifecycleState(state_raw)
    else:
        state_val = SubgoalLifecycleState.PENDING
    return Subgoal(
        subgoal_id=str(raw.get("subgoal_id", "placeholder_subgoal")),
        goal=str(raw.get("goal", "placeholder_goal")),
        context=dict(raw.get("context", {})),
        metadata=dict(raw.get("metadata", {})),
        parent_id=raw.get("parent_id"),
        state=state_val,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Action execution
# ──────────────────────────────────────────────────────────────────────────────

# Mapping from arbitration action → which budget scopes to charge
_ACTION_SCOPE_CHARGE: Dict[str, List[str]] = {
    "repair": ["cycle", "global"],
    "replan": ["cycle", "plan", "global"],
    "regen_segment": ["cycle", "subgoal", "global"],
    "regen_subgoal": ["cycle", "subgoal", "global"],
    "catastrophic": ["cycle", "global"],
}


def _execute_action(
    action: str,
    plan_state: PlanState,
    plan: Plan,
    segment: PlanSegment,
    subgoal: Subgoal,
) -> Dict[str, Any]:
    """Execute the arbitration action and return a JSON‑safe result."""
    if action == "none":
        return {
            "action": "none",
            "message": "No drift detected — no action taken.",
        }
    elif action == "repair":
        repaired = repair_drift_inconsistency(plan_state)
        return {
            "action": "repair",
            "repaired_plan_state": _to_json_safe(repaired),
        }
    elif action == "replan":
        placeholder = Plan(
            intent="PLACEHOLDER_REPLAN_INTENT",
            targetskillid="replanned_skill",
            arguments={"reason": "budget_exhausted_or_major_drift"},
            reasoning_summary="Regenerated placeholder plan via harness replan action",
        )
        repaired_plan = repair_plan(placeholder)
        return {
            "action": "replan",
            "placeholder_plan": _to_json_safe(repaired_plan),
        }
    elif action == "regen_segment":
        placeholder = PlanSegment(
            subgoal_id="regenerated_segment",
            steps=["validate", "execute", "verify"],
            context={"source": "harness_regen_segment"},
            metadata={"regenerated": True},
        )
        repaired_segment = repair_segment(placeholder)
        return {
            "action": "regen_segment",
            "placeholder_segment": _to_json_safe(repaired_segment),
        }
    elif action == "regen_subgoal":
        placeholder = Subgoal(
            subgoal_id="regenerated_subgoal",
            goal="Regenerated subgoal via harness",
            context={"source": "harness_regen_subgoal"},
            metadata={"regenerated": True},
            state=SubgoalLifecycleState.PENDING,
        )
        repaired_subgoal = repair_subgoal(placeholder)
        return {
            "action": "regen_subgoal",
            "placeholder_subgoal": _to_json_safe(repaired_subgoal),
        }
    elif action == "catastrophic":
        return {
            "action": "catastrophic",
            "catastrophic_envelope": {
                "status": "catastrophic_recovery_required",
                "severity": "catastrophic",
                "message": (
                    "Escalation to catastrophic recovery — plan regeneration "
                    "or full reset required.  Current plan state preserved for "
                    "forensic analysis."
                ),
                "preserved_plan_state": _to_json_safe(plan_state),
                "preserved_plan": _to_json_safe(plan),
                "preserved_segment": _to_json_safe(segment),
                "preserved_subgoal": _to_json_safe(subgoal),
            },
        }
    else:
        return {"action": action, "error": f"Unknown action: {action!r}"}


def _update_budgets(
    budgets: RepairBudgetState,
    action: str,
) -> RepairBudgetState:
    """Apply budget charges for *action* and return a new state.

    Skips scopes that are already exhausted rather than raising.
    """
    state = budgets
    scopes = _ACTION_SCOPE_CHARGE.get(action, ["cycle", "global"])
    for scope in scopes:
        if is_budget_exhausted(state, scope):
            continue  # Already exhausted — no further charge
        state = apply_repair_budget(state, scope)
    return state


# ──────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────────────────────────

def run_pipeline(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Run the full drift‑to‑repair pipeline on *input_data*.

    Parameters
    ----------
    input_data
        Parsed JSON dict from stdin.  Expected fields:

        * ``signals`` (required) — list of ``UnifiedDriftSignal`` dicts
        * ``budget_config`` — ``RepairBudgetConfig`` dict (optional)
        * ``budget_usage`` — ``RepairBudgetState`` usage dict (optional)
        * ``plan_state`` — ``PlanState`` dict for repair (optional)
        * ``plan`` — ``Plan`` dict (optional)
        * ``segment`` — ``PlanSegment`` dict (optional)
        * ``subgoal`` — ``Subgoal`` dict (optional)
        * ``previous_classification`` — previous ``UnifiedDriftClassification``
          dict (optional)

    Returns
    -------
    dict
        The complete state‑transition trace, keyed by section name.
    """
    # ── Parse inputs ─────────────────────────────────────────────────────
    if "signals" not in input_data:
        _fatal("Missing required field 'signals' in input.")
    signals_raw: List[Dict[str, Any]] = list(input_data["signals"])

    budget_config = _build_budget_config(input_data.get("budget_config"))
    budgets = _build_budget_state(budget_config, input_data.get("budget_usage"))
    previous = _build_classification(input_data.get("previous_classification"))
    plan_state = _build_plan_state(input_data.get("plan_state"))
    plan = _build_plan(input_data.get("plan"))
    segment = _build_segment(input_data.get("segment"))
    subgoal = _build_subgoal(input_data.get("subgoal"))

    # ── Record original input for trace ──────────────────────────────────
    input_snapshot = {
        "signal_count": len(signals_raw),
        "signals_preview": [
            {"source": s.get("source"), "type": s.get("type"), "weight": s.get("weight")}
            for s in signals_raw[:10]
        ],
    }

    # ── 1. Drift classification ──────────────────────────────────────────
    signals = _build_signals(signals_raw)
    classification = classify_unified_drift(signals, previous)

    # ── 2. Arbitration ───────────────────────────────────────────────────
    decision = decide_arbitration_action(
        classification, budgets, plan_state, subgoal, segment,
    )

    # ── 3. Execute action ────────────────────────────────────────────────
    action_output = _execute_action(
        decision.action, plan_state, plan, segment, subgoal,
    )

    # ── 4. Update budgets (skip for "none" action) ────────────────────────
    if decision.action == "none":
        updated_budgets = budgets  # No budget charge for no-op
    else:
        updated_budgets = _update_budgets(budgets, decision.action)

    return {
        "INPUT": input_snapshot,
        "DRIFT_CLASSIFICATION": classification,
        "ARBITRATION_DECISION": decision,
        "ACTION_OUTPUT": action_output,
        "UPDATED_BUDGET": updated_budgets,
    }


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Read JSON from stdin, run the pipeline, and print the trace."""
    # Read all of stdin
    raw_input = sys.stdin.read()
    if not raw_input.strip():
        _fatal("Empty stdin — provide JSON input.")

    try:
        input_data = json.loads(raw_input)
    except json.JSONDecodeError as exc:
        _fatal(f"Invalid JSON input: {exc}")

    if not isinstance(input_data, dict):
        _fatal(f"Expected a JSON object, got {type(input_data).__name__}")

    trace = run_pipeline(input_data)

    # Print sections in deterministic order
    for section_name in (
        "INPUT",
        "DRIFT_CLASSIFICATION",
        "ARBITRATION_DECISION",
        "ACTION_OUTPUT",
        "UPDATED_BUDGET",
    ):
        _print_section(section_name, trace[section_name])


if __name__ == "__main__":
    main()
