"""
R.11.4 — Plan Step Executor (S5/S6)
====================================

Replaces the old S2 ``PlanExecutor`` which violated stratum isolation by
performing I/O inside the planning stratum.

The ``PlanStepExecutor`` lives in S5/S6 and routes plan steps to S3 via
the ``S3SkillExecutor`` protocol interface.  S2 remains pure — it generates
and validates plans but never executes them.
"""

from __future__ import annotations

from typing import Any, Dict

from src.agent.interfaces.s3_executor import S3SkillExecutor
from src.strategy.planning.models.plan import Plan
from src.strategy.types.cognitive_step_outcome import CognitiveStepOutcome
from src.strategy.types.step_result import StepResult


class PlanStepExecutor:
    """Executes a single Plan step by routing it to S3.

    This is the S5/S6 replacement for the old S2 PlanExecutor.  It takes
    a ``Plan`` (produced by S2), extracts the target skill and arguments,
    and calls ``S3SkillExecutor.execute()`` to run the skill.

    The result is wrapped in a ``StepResult`` compatible with S2's
    outcome model.
    """

    def __init__(self, skill_executor: S3SkillExecutor) -> None:
        self._skill_executor = skill_executor

    def execute(self, plan: Plan) -> StepResult:
        """Execute a plan by routing its target skill to S3.

        Args:
            plan: A validated Plan from S2 with ``targetskillid`` and
                  ``arguments``.

        Returns:
            A ``StepResult`` with ``SUCCESS`` outcome on success, or
            ``FAILURE`` on error.
        """
        result = self._skill_executor.execute(
            skill_name=plan.targetskillid,
            arguments=plan.arguments,
        )

        if result.success and result.output is not None:
            return StepResult(
                outcome=CognitiveStepOutcome.SUCCESS,
                reason="plan executed successfully",
                payload=result.output,
                trace={},
            )
        else:
            return StepResult(
                outcome=CognitiveStepOutcome.FAILURE,
                reason=result.error or "skill execution failed",
                payload={},
                trace={},
            )
