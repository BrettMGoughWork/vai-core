"""Integration tests for PlanExecutor execute() — decoupled from S3.

Validates that execute() correctly:
  - Returns success when the dispatcher succeeds.
  - Returns failure when the dispatcher returns a non-success outcome.
  - Returns terminal metrics in both cases.
"""

from __future__ import annotations

from unittest.mock import Mock

from src.strategy.planning.dispatch.plan_executor import PlanExecutor, PlanExecutorMetrics
from src.strategy.planning.dispatch.safe_step_dispatcher import SafeStepDispatcher
from src.strategy.planning.models.plan import Plan
from src.strategy.planning.models.step_state import StepState, StepStatus
from src.strategy.types.step_result import StepResult
from src.strategy.types.cognitive_step_outcome import CognitiveStepOutcome


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


def make_success_result() -> StepResult:
    return StepResult(
        outcome=CognitiveStepOutcome.SUCCESS,
        reason="done",
        payload={"x": 1},
        trace=[],
    )


def make_failure_result() -> StepResult:
    return StepResult(
        outcome=CognitiveStepOutcome.FAILURE,
        reason="fatal error in skill",
        payload={},
        trace=[],
    )


def _sample_state() -> StepState:
    """A minimal valid StepState (dispatcher contract requires non-None state)."""
    return StepState(
        step_id="test-step",
        parent_id=None,
        cognitive_input={},
        last_result=None,
        status=StepStatus.PENDING,
        created_at=0,
        attempt=0,
        trace=[],
        canonical_hash="test",
    )


def make_mock_dispatcher() -> Mock:
    dispatcher = Mock(spec=SafeStepDispatcher)
    dispatcher.dispatch.return_value = (
        _sample_state(),
        make_success_result(),
    )
    return dispatcher


def make_fail_dispatcher() -> Mock:
    dispatcher = Mock(spec=SafeStepDispatcher)
    dispatcher.dispatch.return_value = (
        _sample_state(),
        make_failure_result(),
    )
    return dispatcher


# ── Tests ─────────────────────────────────────────────────────────────

def test_execute_returns_success():
    """execute() returns success metrics when the dispatcher succeeds."""
    executor = PlanExecutor(dispatcher=make_mock_dispatcher())
    plan = make_plan(skill="json.parse")

    state, result, metrics = executor.execute(plan)

    assert metrics.termination_reason == "success"
    assert result.outcome == CognitiveStepOutcome.SUCCESS


def test_execute_returns_failure():
    """execute() returns failure metrics when the dispatcher fails."""
    executor = PlanExecutor(dispatcher=make_fail_dispatcher())
    plan = make_plan(skill="fail.skill")

    state, result, metrics = executor.execute(plan)

    assert metrics.termination_reason == "failure"
    assert result.outcome != CognitiveStepOutcome.SUCCESS
    assert "fatal" in result.reason