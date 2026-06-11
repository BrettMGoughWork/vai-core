from src.strategy.planning.models.plan_state import PlanState, PlanStatus

class PlanStateValidationError(Exception):
    pass


def validate_plan_state(state: PlanState) -> None:
    if state.current_step_index < 0:
        raise PlanStateValidationError("current_step_index cannot be negative")

    if state.current_step_index >= len(state.steps):
        raise PlanStateValidationError(
            f"current_step_index {state.current_step_index} out of bounds"
        )

    if not isinstance(state.status, PlanStatus):
        raise PlanStateValidationError("Invalid plan status")

    # Additional invariants for future multi-step planning
    if state.status == PlanStatus.COMPLETED and state.last_result is None:
        raise PlanStateValidationError("Completed plan must have a last_result")