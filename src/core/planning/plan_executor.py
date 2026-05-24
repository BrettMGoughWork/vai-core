from dataclasses import dataclass

from src.core.planning.safe_step_dispatcher import SafeStepDispatcher
from src.core.planning.plan_state import PlanState
from src.core.planning.plan_errors import PlanDispatchError, PlanValidationError, PlanExecutionError
from src.core.planning.step_dispatcher import StepDispatcher
from src.core.loop import CoreStepV2, StepState, StepResult, StepOutcome
from src.core.planning.plan import Plan

@dataclass(frozen=True)
class PlanExecutorMetrics:
    duration: int
    termination_reason: str


class PlanExecutor:
    """
    Executes a validated plan and returns:
    - final StepState
    - final StepResult
    - PlanExecutorMetrics
    """

    def __init__(self, dispatcher: SafeStepDispatcher):
        self.dispatcher = dispatcher

    def execute(self, plan: Plan) -> tuple[StepState, StepResult, PlanExecutorMetrics]:
        start = 0
        state, result = self.dispatcher.dispatch(plan)
        try:
            state, result = self.dispatcher.dispatch(plan)
        except Exception as exc:
            # catastrophic substrate error
            result = StepResult.failure(
                reason=str(exc),
                payload={"error_type": "PlanExecutorInternalError"},
                trace=[],
            )
            metrics = PlanExecutorMetrics(
                duration=0,
                termination_reason="internal_error",
            )
            return state, result, metrics

        # Map unexpected outcomes to plan-level errors
        if result.outcome != StepOutcome.SUCCESS:
            error = self._map_step_error(result)
            failure_result = StepResult.failure(
                reason=str(error),
                payload={"error_type": type(error).__name__},
                trace=result.trace,
            )
            metrics = PlanExecutorMetrics(
                duration=state.created_at,
                termination_reason="failure",
            )
            return state, failure_result, metrics

        # Success
        metrics = PlanExecutorMetrics(
            duration=state.created_at,
            termination_reason="success",
        )
        return state, result, metrics

    def _map_step_error(self, result: StepResult) -> PlanValidationError:
        if result.outcome == StepOutcome.FAILURE:
            return PlanExecutionError(result.reason)

        if result.outcome in (StepOutcome.CONTINUE, StepOutcome.TOOL_NEEDED):
            return PlanDispatchError(
                f"Unexpected step outcome during plan execution: {result.outcome}"
            )

        return PlanDispatchError("Unknown execution error")