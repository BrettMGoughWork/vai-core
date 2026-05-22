from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional

from .step_result import StepResult, StepOutcome


TerminationReason = Literal[
    "success",
    "failure",
    "tool_needed",
    "continue",
    "step_budget_exceeded",
    "duration_budget_exceeded",
    "policy_violation",
]


@dataclass(frozen=True)
class LoopTerminationDecision:
    should_terminate: bool
    reason: TerminationReason


def decide_termination(
    result: StepResult,
    step_count: int,
    max_steps: Optional[int],
    elapsed: int,
    max_duration: Optional[int],
    policy_allows_continue: bool,
) -> LoopTerminationDecision:
    # Terminal outcomes
    if result.outcome == StepOutcome.SUCCESS:
        return LoopTerminationDecision(True, "success")

    if result.outcome == StepOutcome.FAILURE:
        return LoopTerminationDecision(True, "failure")

    if result.outcome == StepOutcome.TOOL_NEEDED:
        return LoopTerminationDecision(True, "tool_needed")

    # Outcome == CONTINUE: check budgets + policy
    if max_steps is not None and step_count >= max_steps:
        return LoopTerminationDecision(True, "step_budget_exceeded")

    if max_duration is not None and elapsed >= max_duration:
        return LoopTerminationDecision(True, "duration_budget_exceeded")

    if not policy_allows_continue:
        return LoopTerminationDecision(True, "policy_violation")

    # Continue loop
    return LoopTerminationDecision(False, "continue")