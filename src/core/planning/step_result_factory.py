from src.core.planning.step_result import StepResult, StepOutcome
from src.core.types.errors import ValidationError
from src.core.types.validation import validate_pure_structure


def success(reason: str, payload=None) -> StepResult:
    payload = payload or {}
    validate_pure_structure(payload)
    return StepResult(
        outcome=StepOutcome.SUCCESS,
        reason=reason,
        payload=payload,
    )


def failure(reason: str, payload=None) -> StepResult:
    payload = payload or {}
    validate_pure_structure(payload)
    return StepResult(
        outcome=StepOutcome.FAILURE,
        reason=reason,
        payload=payload,
    )


def tool_needed(reason: str, payload) -> StepResult:
    if not payload or "tool" not in payload:
        raise ValidationError("tool_needed requires payload['tool']")
    validate_pure_structure(payload)
    return StepResult(
        outcome=StepOutcome.TOOL_NEEDED,
        reason=reason,
        payload=payload,
    )


def continue_reasoning(reason: str, payload=None) -> StepResult:
    payload = payload or {}
    validate_pure_structure(payload)
    return StepResult(
        outcome=StepOutcome.CONTINUE,
        reason=reason,
        payload=payload,
    )