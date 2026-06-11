from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from src.strategy.planning.models.plan import Plan
from src.strategy.planning.models.plan_state import PlanState, PlanStatus
from src.strategy.types.errors.plan_errors import (
    PlanSafetyPolicyError,
    PlanTransitionSafetyError,
)
from src.strategy.planning.step_processor import StepResult # adjust import if needed


@dataclass(frozen=True)
class SafetyContext:
    plan: Plan
    capability: Dict[str, Any]
    plan_state: Optional[PlanState]


class SafetyPolicy(Protocol):
    def pre_execute(self, ctx: SafetyContext) -> None:
        ...

    def post_execute(self, ctx: SafetyContext, result: StepResult) -> None:
        ...


class ForbiddenCapabilityPolicy:
    def __init__(self, forbidden_capabilities: set[str]):
        self.forbidden_capabilities = forbidden_capabilities

    def pre_execute(self, ctx: SafetyContext) -> None:
        if ctx.plan.targetskillid in self.forbidden_capabilities:
            raise PlanSafetyPolicyError(
                f"Capability '{ctx.plan.targetskillid}' is forbidden by safety policy"
            )

    def post_execute(self, ctx: SafetyContext, result: StepResult) -> None:
        return


class PlanTransitionPolicy:
    def pre_execute(self, ctx: SafetyContext) -> None:
        if ctx.plan_state is None:
            return
        if ctx.plan_state.status not in (PlanStatus.PENDING, PlanStatus.RUNNING):
            raise PlanTransitionSafetyError(
                f"Cannot execute plan in status {ctx.plan_state.status}"
            )

    def post_execute(self, ctx: SafetyContext, result: StepResult) -> None:
        return