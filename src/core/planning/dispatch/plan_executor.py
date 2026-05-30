from dataclasses import dataclass

from src.core.planning.dispatch.safe_step_dispatcher import SafeStepDispatcher
from src.core.planning.models.plan_state import PlanState
from src.core.types.errors.plan_errors import PlanDispatchError, PlanValidationError, PlanExecutionError
from src.core.planning.models.step_state import StepState
from src.core.types.step_result import StepResult, StepOutcome
from src.core.planning.models.plan import Plan
from src.core.planning.safety.purity_enforcer import enforce_cognitive_purity

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

    def execute(
        self, 
        plan: Plan,
        plan_state: PlanState | None = None
    ) -> tuple[StepState, StepResult, PlanExecutorMetrics]:
        
        start = 0

        state = PlanState.initial(plan)

        state = PlanState.initial(plan)
        try:
            state, result = self.dispatcher.dispatch(plan, plan_state=plan_state)
        except Exception as exc:
            # catastrophic substrate error
            import traceback
            print("[PlanExecutorInternalError] Exception type:", type(exc).__name__)
            print("[PlanExecutorInternalError] Exception message:", exc)
            print("[PlanExecutorInternalError] Traceback:")
            traceback.print_exc()
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
        # Enforce purity only on capability outputs (result.payload if dict)
        if isinstance(result.payload, dict):
            enforce_cognitive_purity(result.payload)
        metrics = PlanExecutorMetrics(
            duration=state.created_at,
            termination_reason="success",
        )
        # Mark plan as complete
        from src.core.planning.models.plan_state import PlanStatus
        completed_state = state.__class__(
            plan_id=state.plan_id,
            steps=state.steps,
            current_step_index=state.current_step_index,
            status=PlanStatus.COMPLETED,
            last_result=state.last_result,
            trace=state.trace,
            created_at=state.created_at,
            updated_at=state.updated_at,
        )
        return completed_state, result, metrics

    def _map_step_error(self, result: StepResult) -> PlanValidationError:
        if result.outcome == StepOutcome.FAILURE:
            return PlanExecutionError(result.reason)

        if result.outcome in (StepOutcome.CONTINUE, StepOutcome.TOOL_NEEDED):
            return PlanDispatchError(
                f"Unexpected step outcome during plan execution: {result.outcome}"
            )

        return PlanDispatchError("Unknown execution error")