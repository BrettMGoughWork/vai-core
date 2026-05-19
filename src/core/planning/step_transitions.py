from core.planning.step_state import StepState, StepStatus
from core.types.validation import validate_pure_structure


def to_running(state: StepState) -> StepState:
    return state.replace(status=StepStatus.RUNNING)


def to_done(state: StepState, result: dict) -> StepState:
    validate_pure_structure(result)
    return state.replace(
        status=StepStatus.DONE,
        last_result=result,
    )


def to_error(state: StepState, error: dict) -> StepState:
    validate_pure_structure(error)
    return state.replace(
        status=StepStatus.ERROR,
        last_result=error,
    )
