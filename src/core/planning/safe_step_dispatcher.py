from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
        from src.core.planning.step_dispatcher import StepDispatcher

from src.core.types.step_state import StepState
from src.core.planning.plan_state import PlanState
from src.core.types.step_result import StepResult
from src.core.planning.safety_policies import SafetyContext

class SafeStepDispatcher:
    """
    Wraps StepDispatcher with safety checks.
    """

    def __init__(self, dispatcher: "StepDispatcher", safety_policies: list[SafetyPolicy]):
        self.dispatcher = dispatcher
        self.safety_policies = safety_policies

    def dispatch(self, plan: Plan, plan_state: PlanState | None = None) -> tuple[StepState, StepResult]:
        capability = self.dispatcher.core_step.capabilities.get(plan.targetskillid, {})
        ctx = SafetyContext(plan=plan, capability=capability, plan_state=plan_state)

        # pre-execution safety
        for policy in self.safety_policies:
            policy.pre_execute(ctx)

        state, result = self.dispatcher.dispatch(plan)

        # post-execution safety
        for policy in self.safety_policies:
            policy.post_execute(ctx, result)

        return state, result