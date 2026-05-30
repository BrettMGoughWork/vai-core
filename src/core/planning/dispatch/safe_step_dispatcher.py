from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.dispatcher import AgentDispatcher
    from src.core.state.state import ConversationState

from src.core.planning.safety.safety_policies import SafetyContext, SafetyPolicy


class SafeStepDispatcher:
    """
    Wraps a modern StepDispatcher (e.g., AgentDispatcher) with safety checks.
    Compatible with the new dispatcher API: dispatch(state) -> step.
    """

    def __init__(self, dispatcher: "AgentDispatcher", policies: list[SafetyPolicy]):
        self.dispatcher = dispatcher
        self.safety_policies = policies

    def dispatch(self, state: "ConversationState"):
        """
        New API:
            - dispatcher.dispatch(state) -> step
            - safety policies run pre/post around the step
        """

        # Build a minimal safety context for the new architecture
        ctx = SafetyContext(
            plan=None, # old plan model removed
            capability=None, # no capability map in new dispatcher
            plan_state=None # no plan state in new architecture
        )

        # pre-execution safety
        for policy in self.safety_policies:
            policy.pre_execute(ctx)

        # delegate to underlying dispatcher
        step = self.dispatcher.dispatch(state)

        # post-execution safety
        for policy in self.safety_policies:
            policy.post_execute(ctx, step)

        return step
