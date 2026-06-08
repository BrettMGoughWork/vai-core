from __future__ import annotations
from typing import TYPE_CHECKING

from src.core.planning.safety.safety_policies import SafetyContext, SafetyPolicy


class SafeStepDispatcher:
    """
    Wraps a dispatcher with safety policies.

    Supports wrapping either:
      - StepDispatcher  (plan-level):  dispatch(plan) -> (StepState, StepResult)
      - AgentDispatcher (agent-level): dispatch(state) -> step dict

    PlanExecutor calls:  dispatch(plan, plan_state=None) -> (StepState, StepResult)
    The inner dispatcher determines the return shape.
    """

    def __init__(self, dispatcher, policies: list[SafetyPolicy]):
        self.dispatcher = dispatcher
        self.safety_policies = policies

    def dispatch(self, plan, plan_state=None):
        """
        Apply safety policies around plan dispatch.

        Accepts the PlanExecutor calling convention:
            dispatch(plan, plan_state=None) -> dispatched result

        The inner dispatcher receives dispatch(plan).
        SafetyContext is populated from the Plan when available.
        """

        # Build safety context — extract plan if present
        ctx = SafetyContext(
            plan=plan if hasattr(plan, "targetskillid") else None,
            capability=None,
            plan_state=plan_state,
        )

        # pre-execution safety
        for policy in self.safety_policies:
            policy.pre_execute(ctx)

        # delegate to underlying dispatcher
        result = self.dispatcher.dispatch(plan)

        # post-execution safety
        for policy in self.safety_policies:
            policy.post_execute(ctx, result)

        return result
