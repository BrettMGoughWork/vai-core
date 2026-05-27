from __future__ import annotations
from typing import Any, Dict, Optional

from src.core.planning.models.step_state import StepState
from src.core.types.validation import validate_pure_structure
from src.core.types.errors import ValidationError


def validate_cognitive_input(
    state: StepState,
    last_result: Optional[Dict[str, Any]],
    memory_snapshot: Dict[str, Any],
) -> None:
    """
    Enforces the Stratum‑2 cognitive input contract:
    - state: StepState (already pure/deterministic)
    - last_result: optional StepResult (already pure/deterministic)
    - memory_snapshot: JSON‑pure, read-only
    """
    # StepState / StepResult invariants are enforced in their own __post_init__,
    # so here we only need to validate the memory snapshot.
    try:
        validate_pure_structure(memory_snapshot)
    except Exception as e:
        raise ValidationError(f"Memory snapshot is not pure: {e}")


ALLOWED_TYPES = {
    "classification",
    "subgoal",
    "segment",
    "plan",
    "error",
}


def validate_cognitive_output(output: Dict[str, Any]) -> None:
    """
    Enforces the Stratum‑2 cognitive output contract.
    Output must be JSON‑pure and one of the allowed shapes.
    """
    try:
        validate_pure_structure(output)
    except Exception as e:
        raise ValidationError(f"Cognitive output is not pure: {e}")

    t = output.get("type")
    if t not in ALLOWED_TYPES:
        raise ValidationError(f"Invalid cognitive output type: {t!r}")

    if t == "classification":
        _validate_classification(output)
    elif t == "subgoal":
        _validate_subgoal(output)
    elif t == "segment":
        _validate_segment(output)
    elif t == "plan":
        _validate_plan(output)
    elif t == "error":
        _validate_error(output)

def _require_keys(obj: Dict[str, Any], keys: set[str], kind: str) -> None:
    missing = keys - obj.keys()
    if missing:
        raise ValidationError(f"{kind} missing required keys: {sorted(missing)}")


def _validate_classification(o: Dict[str, Any]) -> None:
    _require_keys(o, {"type", "outcome", "reason", "payload"}, "classification")
    if not isinstance(o["reason"], str):
        raise ValidationError("classification.reason must be a string")
    if o["outcome"] not in {"success", "failure", "tool_needed", "continue"}:
        raise ValidationError(f"invalid classification.outcome: {o['outcome']!r}")


def _validate_subgoal(o: Dict[str, Any]) -> None:
    _require_keys(o, {"type", "goal", "context"}, "subgoal")
    if not isinstance(o["goal"], str):
        raise ValidationError("subgoal.goal must be a string")


def _validate_segment(o: Dict[str, Any]) -> None:
    _require_keys(o, {"type", "steps", "context"}, "segment")
    if not isinstance(o["steps"], list):
        raise ValidationError("segment.steps must be a list")


def _validate_plan(o: Dict[str, Any]) -> None:
    _require_keys(o, {"type", "root", "nodes", "metadata"}, "plan")
    if not isinstance(o["nodes"], list):
        raise ValidationError("plan.nodes must be a list")


def _validate_error(o: Dict[str, Any]) -> None:
    _require_keys(o, {"type", "error_type", "message", "details"}, "error")
    if not isinstance(o["message"], str):
        raise ValidationError("error.message must be a string")
    if not isinstance(o["error_type"], str):
        raise ValidationError("error.error_type must be a string")
    if not isinstance(o["details"], dict):
        raise ValidationError("error.details must be a dictionary")