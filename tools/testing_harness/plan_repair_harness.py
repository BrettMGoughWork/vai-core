"""
Phase 2.10.x — Stratum‑2 Plan Repair Harness
=============================================

Deterministic, stdin‑driven CLI tool for exercising the structural repair
pipeline on plans, segments, and subgoals.

Accepts malformed plan/segment/subgoal JSON, classifies drift, arbitrates,
executes repair/regeneration actions, and prints a minimal state‑transition
trace.

Pure, deterministic, JSON‑safe — never calls an LLM, never mutates inputs.
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure the project root is on sys.path so ``from src.…`` imports work
# regardless of how the harness is invoked.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.core.planning.drift.unified_drift_types import (
    UnifiedDriftClassification,
    UnifiedDriftSignal,
)
from src.core.planning.drift.unified_drift_classifier import classify_unified_drift
from src.core.planning.drift.repair_arbitration import (
    ArbitrationDecision,
    decide_arbitration_action,
)
from src.core.planning.drift.repair_action_library import (
    repair_plan,
    repair_segment,
    repair_subgoal,
    normalize_steps,
)
from src.core.planning.drift.repair_budget import (
    RepairBudgetConfig,
    RepairBudgetState,
    apply_repair_budget,
    is_budget_exhausted,
)
from src.core.planning.models.plan import Plan
from src.core.planning.models.plan_state import PlanState, PlanStatus
from src.core.types.plan_segment import PlanSegment
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fatal(msg: str) -> None:
    """Print a fatal error and exit with code 1."""
    print(f"=== ERROR ===\n{msg}", file=sys.stderr)
    sys.exit(1)


def _try_build(value: Any, target: str) -> Any:
    """Attempt to build a dataclass from a raw dict. Returns ``(instance, errors)``."""
    errors: List[str] = []
    try:
        if target == "plan":
            return _build_plan(value, errors)
        elif target == "segment":
            return _build_segment(value, errors)
        elif target == "subgoal":
            return _build_subgoal(value, errors)
        else:
            _fatal(f"Unknown target: {target}")
    except (TypeError, ValueError, KeyError) as exc:
        errors.append(str(exc))
        return None, errors


def _build_plan(raw: Dict[str, Any], errors: List[str]) -> Optional[Plan]:
    """Build a Plan from a dict, collecting structural errors."""
    intent = raw.get("intent")
    if not intent or not isinstance(intent, str):
        errors.append("Plan missing required field 'intent' (non‑empty str)")
    targetskillid = raw.get("targetskillid")
    if not targetskillid or not isinstance(targetskillid, str):
        errors.append("Plan missing required field 'targetskillid' (non‑empty str)")
    arguments = raw.get("arguments")
    if not isinstance(arguments, dict):
        errors.append("Plan 'arguments' must be a dict")
        arguments = {}
    reasoning = raw.get("reasoning_summary")
    if not isinstance(reasoning, str):
        errors.append("Plan 'reasoning_summary' must be a str")
        reasoning = ""

    if errors:
        return None
    return Plan(
        intent=intent,
        targetskillid=targetskillid,
        arguments=arguments,
        reasoning_summary=reasoning,
    )


def _build_segment(raw: Dict[str, Any], errors: List[str]) -> Optional[PlanSegment]:
    """Build a PlanSegment from a dict, collecting structural errors."""
    subgoal_id = raw.get("subgoal_id")
    if not subgoal_id or not isinstance(subgoal_id, str):
        errors.append("Segment missing required field 'subgoal_id' (non‑empty str)")
    steps = raw.get("steps")
    if not isinstance(steps, list):
        errors.append("Segment 'steps' must be a list")
        steps = []
    # Validate steps are all strings
    for i, s in enumerate(steps):
        if not isinstance(s, str):
            errors.append(f"Segment step[{i}] is not a str: {type(s).__name__}")
    valid_steps = [s for s in steps if isinstance(s, str)]
    context = raw.get("context", {})
    if not isinstance(context, dict):
        errors.append("Segment 'context' must be a dict")
        context = {}
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        errors.append("Segment 'metadata' must be a dict")
        metadata = {}

    if errors:
        return None
    return PlanSegment(
        subgoal_id=subgoal_id,
        steps=valid_steps,
        context=context,
        metadata=metadata,
    )


def _build_subgoal(raw: Dict[str, Any], errors: List[str]) -> Optional[Subgoal]:
    """Build a Subgoal from a dict, collecting structural errors."""
    sid = raw.get("subgoal_id")
    if not sid or not isinstance(sid, str):
        errors.append("Subgoal missing required field 'subgoal_id' (non‑empty str)")
    goal = raw.get("goal")
    if not goal or not isinstance(goal, str):
        errors.append("Subgoal missing required field 'goal' (non‑empty str)")
    context = raw.get("context", {})
    if not isinstance(context, dict):
        errors.append("Subgoal 'context' must be a dict")
        context = {}
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        errors.append("Subgoal 'metadata' must be a dict")
        metadata = {}

    if errors:
        return None
    return Subgoal(
        subgoal_id=sid,
        goal=goal,
        context=context,
        metadata=metadata,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Structural inspection → drift signals
# ──────────────────────────────────────────────────────────────────────────────

def _inspect_structure(
    input_type: str, raw: Dict[str, Any]
) -> List[UnifiedDriftSignal]:
    """Inspect a raw dict for structural malformations and return drift signals."""
    signals: List[UnifiedDriftSignal] = []
    errors: List[str] = []
    _try_build(raw, input_type)
    # _try_build appends to errors; we need fresh errors
    del errors[:]
    _try_build(raw, input_type)

    if input_type == "plan":
        _check_plan_fields(raw, signals)
    elif input_type == "segment":
        _check_segment_fields(raw, signals)
    elif input_type == "subgoal":
        _check_subgoal_fields(raw, signals)
    return signals


def _check_plan_fields(raw: Dict[str, Any], signals: List[UnifiedDriftSignal]) -> None:
    """Check plan fields and emit structural signals for issues."""
    intent = raw.get("intent")
    if not intent or not isinstance(intent, str) or not intent.strip():
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="missing_field",
                weight=0.35,
                decay=1.0,
                confidence=0.7,
                details={"field": "intent", "issue": "missing_or_empty"},
            )
        )
    tid = raw.get("targetskillid")
    if not tid or not isinstance(tid, str) or not tid.strip():
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="missing_field",
                weight=0.35,
                decay=1.0,
                confidence=0.7,
                details={"field": "targetskillid", "issue": "missing_or_empty"},
            )
        )
    args = raw.get("arguments")
    if not isinstance(args, dict):
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="type_mismatch",
                weight=0.3,
                decay=1.0,
                confidence=0.6,
                details={"field": "arguments", "expected": "dict", "got": type(args).__name__},
            )
        )
    reasoning = raw.get("reasoning_summary")
    if not isinstance(reasoning, str):
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="type_mismatch",
                weight=0.25,
                decay=1.0,
                confidence=0.5,
                details={"field": "reasoning_summary", "expected": "str", "got": type(reasoning).__name__},
            )
        )


def _check_segment_fields(raw: Dict[str, Any], signals: List[UnifiedDriftSignal]) -> None:
    """Check segment fields and emit structural signals for issues."""
    sid = raw.get("subgoal_id")
    if not sid or not isinstance(sid, str) or not sid.strip():
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="missing_field",
                weight=0.35,
                decay=1.0,
                confidence=0.7,
                details={"field": "subgoal_id", "issue": "missing_or_empty"},
            )
        )
    steps = raw.get("steps")
    if not isinstance(steps, list):
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="type_mismatch",
                weight=0.35,
                decay=1.0,
                confidence=0.7,
                details={"field": "steps", "expected": "list", "got": type(steps).__name__},
            )
        )
    else:
        for i, s in enumerate(steps):
            if s is None:
                signals.append(
                    UnifiedDriftSignal(
                        source="structural",
                        type="null_step",
                        weight=0.3,
                        decay=1.0,
                        confidence=0.6,
                        details={"step_index": i, "issue": "null"},
                    )
                )
            elif not isinstance(s, str):
                signals.append(
                    UnifiedDriftSignal(
                        source="structural",
                        type="type_mismatch",
                        weight=0.3,
                        decay=1.0,
                        confidence=0.6,
                        details={"step_index": i, "expected": "str", "got": type(s).__name__},
                    )
                )
    ctx = raw.get("context")
    if ctx is not None and not isinstance(ctx, dict):
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="type_mismatch",
                weight=0.25,
                decay=1.0,
                confidence=0.5,
                details={"field": "context", "expected": "dict", "got": type(ctx).__name__},
            )
        )


def _check_subgoal_fields(raw: Dict[str, Any], signals: List[UnifiedDriftSignal]) -> None:
    """Check subgoal fields and emit structural signals for issues."""
    sid = raw.get("subgoal_id")
    if not sid or not isinstance(sid, str) or not sid.strip():
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="missing_field",
                weight=0.35,
                decay=1.0,
                confidence=0.7,
                details={"field": "subgoal_id", "issue": "missing_or_empty"},
            )
        )
    goal = raw.get("goal")
    if not goal or not isinstance(goal, str) or not goal.strip():
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="missing_field",
                weight=0.4,
                decay=1.0,
                confidence=0.8,
                details={"field": "goal", "issue": "missing_or_empty"},
            )
        )
    ctx = raw.get("context")
    if ctx is not None and not isinstance(ctx, dict):
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="type_mismatch",
                weight=0.25,
                decay=1.0,
                confidence=0.5,
                details={"field": "context", "expected": "dict", "got": type(ctx).__name__},
            )
        )


# ──────────────────────────────────────────────────────────────────────────────
# Object construction (for valid inputs)
# ──────────────────────────────────────────────────────────────────────────────

def _construct_plan(raw: Dict[str, Any]) -> Plan:
    """Construct a Plan from raw dict (with fallback defaults)."""
    return Plan(
        intent=raw.get("intent", ""),
        targetskillid=raw.get("targetskillid", ""),
        arguments=raw.get("arguments") if isinstance(raw.get("arguments"), dict) else {},
        reasoning_summary=raw.get("reasoning_summary") if isinstance(raw.get("reasoning_summary"), str) else "",
    )


def _construct_segment(raw: Dict[str, Any]) -> PlanSegment:
    """Construct a PlanSegment from raw dict (with fallback defaults).

    Uses ``normalize_steps`` from the repair library so that dict‑based steps
    (e.g. ``{"action": "noop"}``) are preserved as deterministic JSON strings
    rather than silently dropped.
    """
    steps = raw.get("steps")
    if not isinstance(steps, list):
        steps = []
    preserved_steps = normalize_steps(steps)
    return PlanSegment(
        subgoal_id=raw.get("subgoal_id") if isinstance(raw.get("subgoal_id"), str) and raw.get("subgoal_id") else "unknown",
        steps=preserved_steps,
        context=raw.get("context") if isinstance(raw.get("context"), dict) else {},
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )


def _construct_subgoal(raw: Dict[str, Any]) -> Subgoal:
    """Construct a Subgoal from raw dict (with fallback defaults)."""
    sid = raw.get("subgoal_id") if isinstance(raw.get("subgoal_id"), str) and raw.get("subgoal_id") else ""
    goal = raw.get("goal") if isinstance(raw.get("goal"), str) and raw.get("goal") else ""
    ctx = raw.get("context") if isinstance(raw.get("context"), dict) else {}
    meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    # If we have missing critical fields, provide defaults so construction works
    if not sid:
        sid = "unknown"
    if not goal:
        goal = "unknown"
    return Subgoal(
        subgoal_id=sid,
        goal=goal,
        context=ctx,
        metadata=meta,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Action execution
# ──────────────────────────────────────────────────────────────────────────────

def _execute_action(
    action: str,
    plan: Plan,
    segment: PlanSegment,
    subgoal: Subgoal,
    input_type: str,
    raw: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute the arbitration decision and return a JSON‑safe result dict.

    For ``repair`` actions the output always contains the **full** repaired
    structure — plan fields plus any segments/scopes that were present in the
    raw input.  Steps inside segments are normalised by ``repair_segment``.
    """
    if action == "none":
        return {"action": "none"}
    elif action == "repair":
        if input_type == "plan":
            repaired_plan = repair_plan(plan)
            result = _plan_to_safe(repaired_plan)
            # If the raw input contained segments, repair each and include them
            segments_raw = raw.get("segments")
            if isinstance(segments_raw, list):
                repaired_segments: List[Dict[str, Any]] = []
                for seg_raw in segments_raw:
                    if isinstance(seg_raw, dict):
                        seg = _construct_segment(seg_raw)
                        repaired_seg = repair_segment(seg)
                        repaired_segments.append(_segment_to_safe(repaired_seg))
                result["segments"] = repaired_segments
            return {"action": "repair", "result": result}
        elif input_type == "segment":
            repaired = repair_segment(segment)
            return {"action": "repair", "result": _segment_to_safe(repaired)}
        elif input_type == "subgoal":
            repaired = repair_subgoal(subgoal)
            return {"action": "repair", "result": _subgoal_to_safe(repaired)}
        else:
            return {"action": "repair", "result": {}}
    elif action == "replan":
        return {"action": "replan", "plan": {"status": "placeholder_replan"}}
    elif action == "regen_segment":
        return {"action": "regen_segment", "segment": {"status": "placeholder_segment"}}
    elif action == "regen_subgoal":
        return {"action": "regen_subgoal", "subgoal": {"status": "placeholder_subgoal"}}
    elif action == "catastrophic":
        return {"action": "catastrophic"}
    else:
        _fatal(f"Unknown arbitration action: {action}")


def _plan_to_safe(plan: Plan) -> Dict[str, Any]:
    """Convert Plan to JSON‑safe dict."""
    return {
        "intent": plan.intent,
        "targetskillid": plan.targetskillid,
        "arguments": deepcopy(plan.arguments),
        "reasoning_summary": plan.reasoning_summary,
    }


def _segment_to_safe(seg: PlanSegment) -> Dict[str, Any]:
    """Convert PlanSegment to JSON‑safe dict.

    Steps that were serialised from dicts (e.g. ``{"action": "noop"}`` → JSON
    string) are parsed back to dicts for human‑readable output.
    """
    return {
        "subgoal_id": seg.subgoal_id,
        "steps": [_step_str_to_safe(s) for s in seg.steps],
        "context": deepcopy(seg.context),
        "metadata": deepcopy(seg.metadata),
    }


def _step_str_to_safe(step_text: str) -> Any:
    """Try to parse a step string as JSON; return dict if successful, else str."""
    if not isinstance(step_text, str):
        return step_text
    stripped = step_text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            pass
    return step_text


def _subgoal_to_safe(sg: Subgoal) -> Dict[str, Any]:
    """Convert Subgoal to JSON‑safe dict."""
    return {
        "subgoal_id": sg.subgoal_id,
        "goal": sg.goal,
        "context": deepcopy(sg.context),
        "metadata": deepcopy(sg.metadata),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Budget handling
# ──────────────────────────────────────────────────────────────────────────────

_ACTION_SCOPE: Dict[str, str] = {
    "repair": "plan",
    "replan": "plan",
    "regen_segment": "subgoal",
    "regen_subgoal": "subgoal",
    "catastrophic": "global",
}


def _update_budgets(budgets: RepairBudgetState, action: str) -> RepairBudgetState:
    """Apply budget charges for the action. Skips exhausted scopes."""
    state = budgets
    # Always charge cycle
    if not is_budget_exhausted(state, "cycle"):
        state = apply_repair_budget(state, "cycle")
    # Charge the action's scope
    scope = _ACTION_SCOPE.get(action, "global")
    if not is_budget_exhausted(state, scope):
        state = apply_repair_budget(state, scope)
    # Always charge global
    if not is_budget_exhausted(state, "global"):
        state = apply_repair_budget(state, "global")
    return state


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline
# ──────────────────────────────────────────────────────────────────────────────

def run_pipeline(raw_input: Dict[str, Any]) -> Dict[str, Any]:
    """Run the full drift‑to‑repair pipeline on raw JSON input.

    Returns a dict keyed by section name, with values being dataclass
    instances or JSON‑safe dicts.
    """
    # ── 0. Detect input type ──
    input_type = None
    input_value = None
    for key in ("plan", "segment", "subgoal"):
        if key in raw_input:
            input_type = key
            input_value = raw_input[key]
            break
    if input_type is None:
        _fatal("Input must contain one of: 'plan', 'segment', 'subgoal'")
    if not isinstance(input_value, dict):
        _fatal(f"Value for '{input_type}' must be a JSON object, got {type(input_value).__name__}")

    # ── 1. Build objects ──
    plan = _construct_plan(input_value) if input_type == "plan" else _construct_plan({})
    segment = _construct_segment(input_value) if input_type == "segment" else _construct_segment({})
    subgoal = _construct_subgoal(input_value) if input_type == "subgoal" else _construct_subgoal({})

    # Build a minimal PlanState for arbitration
    plan_state = PlanState(
        plan_id="harness-plan",
        steps=[],
        current_step_index=0,
        status=PlanStatus.PENDING,
        last_result=None,
        trace=[],
        created_at=0,
        updated_at=0,
    )

    # ── 2. Inspect structure → signals ──
    signals = _inspect_structure(input_type, input_value)

    # ── 3. Drift classification ──
    classification = classify_unified_drift(signals)

    # ── 4. Arbitration ──
    budgets = RepairBudgetState()
    decision = decide_arbitration_action(
        classification, budgets, plan_state, subgoal, segment,
    )

    # ── 5. Execute action ──
    action_output = _execute_action(
        decision.action, plan, segment, subgoal, input_type, input_value,
    )

    # ── 6. Update budgets ──
    if decision.action == "none":
        updated_budgets = budgets
    else:
        updated_budgets = _update_budgets(budgets, decision.action)

    # ── 7. Input snapshot ──
    input_snapshot = {"type": input_type, "raw_summary": _summarise_raw(input_type, input_value)}

    return {
        "INPUT": input_snapshot,
        "DRIFT_CLASSIFICATION": classification,
        "ARBITRATION_DECISION": decision,
        "ACTION_OUTPUT": action_output,
        "UPDATED_BUDGET": updated_budgets,
    }


def _summarise_raw(input_type: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Create a minimal structural summary of the raw input.

    Returns a JSON‑safe dict with:
    * ``type`` — "plan", "segment", or "subgoal"
    * ``segments`` — number of segments (plan only)
    * ``steps`` — total number of steps (plan or segment)
    * ``missing_fields`` — list of missing required fields
    """
    summary: Dict[str, Any] = {"type": input_type}

    if input_type == "plan":
        segments = raw.get("segments")
        if isinstance(segments, list):
            summary["segments"] = len(segments)
            total_steps = 0
            for s in segments:
                if isinstance(s, dict) and isinstance(s.get("steps"), list):
                    total_steps += len(s["steps"])
            summary["steps"] = total_steps
        else:
            summary["segments"] = 0
            summary["steps"] = 0
        missing: List[str] = []
        if not raw.get("intent") or not isinstance(raw.get("intent"), str) or not raw["intent"].strip():
            missing.append("intent")
        if not raw.get("targetskillid") or not isinstance(raw.get("targetskillid"), str) or not raw["targetskillid"].strip():
            missing.append("targetskillid")
        if not isinstance(raw.get("arguments"), dict):
            missing.append("arguments")
        if not isinstance(raw.get("segments"), list):
            missing.append("segments")
        summary.setdefault("missing_fields", missing)

    elif input_type == "segment":
        steps = raw.get("steps")
        summary["steps"] = len(steps) if isinstance(steps, list) else 0
        missing: List[str] = []
        if not isinstance(raw.get("steps"), list):
            missing.append("steps")
        summary.setdefault("missing_fields", missing)

    else:  # subgoal
        missing: List[str] = []
        if not raw.get("goal") or not isinstance(raw.get("goal"), str) or not raw["goal"].strip():
            missing.append("goal")
        summary.setdefault("missing_fields", missing)

    return summary


# ──────────────────────────────────────────────────────────────────────────────
# Output formatting
# ──────────────────────────────────────────────────────────────────────────────

def _to_json(obj: Any) -> Any:
    """Convert a dataclass or dict to a JSON‑safe representation."""
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    return obj


def print_trace(trace: Dict[str, Any]) -> None:
    """Print the pipeline trace in 5‑section format."""
    section_order = [
        "INPUT",
        "DRIFT_CLASSIFICATION",
        "ARBITRATION_DECISION",
        "ACTION_OUTPUT",
        "UPDATED_BUDGET",
    ]
    for section in section_order:
        print(f"=== {section} ===")
        value = _to_json(trace.get(section, {}))
        print(json.dumps(value, indent=2, default=str))


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Read JSON from stdin, run the pipeline, and print the trace."""
    try:
        raw_text = sys.stdin.read()
    except (OSError, UnicodeDecodeError) as exc:
        _fatal(f"Failed to read stdin: {exc}")

    if not raw_text.strip():
        _fatal("No input received on stdin. Provide JSON with 'plan', 'segment', or 'subgoal'.")

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        _fatal(f"Invalid JSON: {exc}")

    if not isinstance(parsed, dict):
        _fatal("Top‑level JSON must be an object, e.g. {\"plan\": {...}}")

    trace = run_pipeline(parsed)
    print_trace(trace)


if __name__ == "__main__":
    main()
