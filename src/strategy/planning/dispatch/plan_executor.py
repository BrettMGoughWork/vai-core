from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.strategy.planning.dispatch.safe_step_dispatcher import SafeStepDispatcher
from src.strategy.planning.models.plan_state import PlanState
from src.strategy.types.errors.plan_errors import PlanDispatchError, PlanValidationError, PlanExecutionError
from src.strategy.planning.models.step_state import StepState
from src.strategy.types.step_result import StepResult
from src.strategy.types.cognitive_step_outcome import CognitiveStepOutcome
from src.strategy.planning.models.plan import Plan
from src.strategy.planning.safety.purity_enforcer import enforce_cognitive_purity

if TYPE_CHECKING:
    from src.strategy.memory.segment_memory import SegmentMemory

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

    def __init__(
        self,
        dispatcher: SafeStepDispatcher,
        runtime_context: dict | None = None,
    ):
        self.dispatcher = dispatcher
        self._runtime_context = runtime_context or {}

    def execute(
        self, 
        plan: Plan,
        plan_state: PlanState | None = None
    ) -> tuple[StepState, StepResult, PlanExecutorMetrics]:
        
        start = int(time() * 1000)

        # The skill to call is the first in the segment's skills list
        # (stored as plan.targetskillid by the planner — segment.skills[0]).
        selected_skill = plan.targetskillid

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
        if result.outcome != CognitiveStepOutcome.SUCCESS:
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
        return state, result, metrics

    def _map_step_error(self, result: StepResult) -> PlanValidationError:
        if result.outcome == CognitiveStepOutcome.FAILURE:
            return PlanExecutionError(result.reason)

        if result.outcome in (CognitiveStepOutcome.CONTINUE, CognitiveStepOutcome.TOOL_NEEDED):
            return PlanDispatchError(
                f"Unexpected step outcome during plan execution: {result.outcome}"
            )

        return PlanDispatchError("Unknown execution error")