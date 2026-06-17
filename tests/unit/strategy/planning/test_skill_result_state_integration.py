"""Integration tests for PlanStepExecutor — decoupled from S3.

Validates that execute() correctly:
  - Returns success when the skill executor succeeds.
  - Returns failure when the skill executor returns an error.
"""

from __future__ import annotations

from unittest.mock import Mock

from src.agent.workflow.plan_step_executor import PlanStepExecutor
from src.agent.interfaces.s3_executor import S3SkillExecutor
from src.strategy.planning.models.plan import Plan
from src.strategy.types.cognitive_step_outcome import CognitiveStepOutcome
from src.strategy.types.step_result import StepResult
from src.capabilities.contracts import SkillResult


# ── Helpers ───────────────────────────────────────────────────────────

def make_plan(
    *,
    intent: str = "test intent",
    skill: str = "json.parse",
    arguments: dict | None = None,
) -> Plan:
    return Plan(
        intent=intent,
        targetskillid=skill,
        arguments=arguments or {"value": "hello"},
        reasoning_summary="test reasoning",
    )


def make_mock_skill_executor(*, success: bool = True) -> Mock:
    executor = Mock(spec=S3SkillExecutor)
    executor.execute.return_value = SkillResult(
        request_id="test",
        success=success,
        output={"x": 1} if success else None,
        error=None if success else "fatal error in skill",
    )
    return executor


# ── Tests ─────────────────────────────────────────────────────────────

def test_execute_returns_success():
    """execute() returns SUCCESS StepResult when the skill succeeds."""
    skill_executor = make_mock_skill_executor(success=True)
    executor = PlanStepExecutor(skill_executor=skill_executor)
    plan = make_plan(skill="json.parse")

    result = executor.execute(plan)

    assert result.outcome == CognitiveStepOutcome.SUCCESS
    assert result.payload == {"x": 1}
    skill_executor.execute.assert_called_once_with(
        skill_name="json.parse",
        arguments={"value": "hello"},
    )


def test_execute_returns_failure():
    """execute() returns FAILURE StepResult when the skill fails."""
    skill_executor = make_mock_skill_executor(success=False)
    executor = PlanStepExecutor(skill_executor=skill_executor)
    plan = make_plan(skill="fail.skill")

    result = executor.execute(plan)

    assert result.outcome == CognitiveStepOutcome.FAILURE
    assert "fatal" in result.reason