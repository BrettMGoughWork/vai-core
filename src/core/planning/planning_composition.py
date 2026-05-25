"""
Initial planning composition root (Phase 2.2.6)

This module exposes a minimal, import-stable assembly of the planning
substrate components. It is intended for internal testing only and is
not integrated into the agent loop.
"""

from src.core.planning.generator.plan_generator import PlanGenerator
from src.core.planning.validators.plan_validator import PlanValidator
from src.core.planning.dispatch.plan_executor import PlanExecutor
from src.core.planning.dispatch.step_dispatcher import StepDispatcher
from src.core.planning.dispatch.safe_step_dispatcher import SafeStepDispatcher
from src.core.planning.safety.safety_policies import (
    ForbiddenCapabilityPolicy,
    PlanTransitionPolicy,
)
from src.core.planning.core_step import CoreStep


def build_planning_substrate():
    """
    Returns a tuple of:
    (plan_generator, plan_validator, plan_executor)

    This is the minimal substrate assembly for internal tests.
    """
    # Core step engine
    capabilities = {
        "dummy": {},
        "echo": {"input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}
    }
    core_step = CoreStep(capabilities=capabilities)

    # Base dispatcher
    dispatcher = StepDispatcher(core_step=core_step)

    # Safety policies (empty forbidden list for now)
    safety_policies = [
        ForbiddenCapabilityPolicy(forbidden_capabilities=set()),
        PlanTransitionPolicy(),
    ]

    # Safety wrapper
    safe_dispatcher = SafeStepDispatcher(
        dispatcher=dispatcher,
        safety_policies=safety_policies,
    )

    # Substrate components
    plan_generator = PlanGenerator(capabilities=capabilities)
    plan_validator = PlanValidator(capabilities=capabilities)
    plan_executor = PlanExecutor(dispatcher=safe_dispatcher)

    return plan_generator, plan_validator, plan_executor