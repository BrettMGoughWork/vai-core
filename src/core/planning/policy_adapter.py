from __future__ import annotations

from .loop_controller import LoopPolicy
from ..types.step_state import StepState
from ..types.step_result import StepResult
from .loop_policy_enforcer import LoopPolicyEnforcer # adjust import if name differs


class EnforcedLoopPolicy(LoopPolicy):
    """
    Adapter from existing LoopPolicyEnforcer to the LoopPolicy protocol.

    Keeps Stratum-2 depending only on an interface, not a concrete implementation.
    """

    def __init__(self, enforcer: LoopPolicyEnforcer) -> None:
        self._enforcer = enforcer

    def allows_continue(
        self,
        state: StepState,
        result: StepResult,
        step_count: int,
    ) -> bool:
        # Adjust this call to match your actual LoopPolicyEnforcer API
        return self._enforcer.allows_continue(state=state, result=result, step_count=step_count)
