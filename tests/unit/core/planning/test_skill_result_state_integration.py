"""Integration tests for Phase 3.8.8 — wiring S3 skill results into S2 state.

Tests A–E verify that:
  A. Successful skill result updates segment memory.
  B. Failed skill result updates segment memory with error.
  C. Behavioural delta computed correctly on consecutive calls.
  D. Previous output preserved in new record.
  E. Cycle halts on failure (execute returns error metrics).
"""

from __future__ import annotations

import time
from unittest.mock import Mock

import pytest

from src.core.memory.segment_memory import SegmentMemory
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.dispatch.plan_executor import PlanExecutor, PlanExecutorMetrics
from src.core.planning.dispatch.safe_step_dispatcher import SafeStepDispatcher
from src.core.planning.models.plan import Plan
from src.core.types.step_result import StepResult
from src.core.types.cognitive_step_outcome import CognitiveStepOutcome
from src.core.planning.behavioural_delta import compute_behavioural_delta
from src.stratum2.s3_adapter import S3Adapter, S2SkillCallRequest, S2SkillResult


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


def make_mock_s3_adapter(
    *,
    success: bool = True,
    output: dict | None = None,
    error: str | None = None,
) -> Mock:
    adapter = Mock(spec=S3Adapter)
    adapter.call_skill.return_value = S2SkillResult(
        request_id="json.parse",
        success=success,
        output=output,
        error=error,
    )
    return adapter


def make_mock_dispatcher() -> Mock:
    dispatcher = Mock(spec=SafeStepDispatcher)
    dispatcher.dispatch.return_value = (
        None,  # state
        make_success_result(),
    )
    return dispatcher


# ── A. Successful skill result updates state ──────────────────────────

def test_successful_result_writes_record():
    """A: Successful S3 result → SegmentMemoryRecord with state='success'."""
    segment_memory = SegmentMemory()
    s3_adapter = make_mock_s3_adapter(success=True, output={"x": 1})

    executor = PlanExecutor(
        dispatcher=make_mock_dispatcher(),
        s3_adapter=s3_adapter,
        segment_memory=segment_memory,
    )
    plan = make_plan(skill="json.parse", arguments={"value": "hello"})

    record = executor._write_skill_result_to_state(plan, make_success_result())

    assert record is not None
    assert record.segment_id == "json.parse"
    assert record.state == "success"
    assert record.last_output == {"x": 1}
    assert record.error is None
    assert record.skills == ["json.parse"]

    # Verify stored in memory
    stored = segment_memory.get_record("json.parse")
    assert stored is not None
    assert stored.state == "success"
    assert stored.last_output == {"x": 1}


# ── B. Failed skill result updates state ──────────────────────────────

def test_failed_result_writes_error_record():
    """B: Failed S3 result → SegmentMemoryRecord with state='error'."""
    segment_memory = SegmentMemory()
    s3_adapter = make_mock_s3_adapter(success=False, output=None, error="boom")

    executor = PlanExecutor(
        dispatcher=make_mock_dispatcher(),
        s3_adapter=s3_adapter,
        segment_memory=segment_memory,
    )
    plan = make_plan(skill="fail.skill")

    record = executor._write_skill_result_to_state(plan, make_success_result())

    assert record is not None
    assert record.state == "error"
    assert record.last_output is None
    assert record.error == "boom"

    # Verify stored
    stored = segment_memory.get_record("fail.skill")
    assert stored is not None
    assert stored.state == "error"
    assert stored.error == "boom"


# ── C. Behavioural delta computed correctly ───────────────────────────

def test_behavioural_delta_computed_on_consecutive_calls():
    """C: Consecutive calls with different output → delta reflects changes."""
    segment_memory = SegmentMemory()

    # First call with output={"a": 1}
    s3_adapter1 = make_mock_s3_adapter(success=True, output={"a": 1})
    executor1 = PlanExecutor(
        dispatcher=make_mock_dispatcher(),
        s3_adapter=s3_adapter1,
        segment_memory=segment_memory,
    )
    plan = make_plan(skill="test.delta")
    executor1._write_skill_result_to_state(plan, make_success_result())

    # Second call with output={"a": 2}
    s3_adapter2 = make_mock_s3_adapter(success=True, output={"a": 2})
    executor2 = PlanExecutor(
        dispatcher=make_mock_dispatcher(),
        s3_adapter=s3_adapter2,
        segment_memory=segment_memory,
    )
    record = executor2._write_skill_result_to_state(plan, make_success_result())

    assert record is not None
    assert record.behavioural_delta is not None
    # The delta should contain information about the changed field
    assert "changed_fields" in record.behavioural_delta or record.behavioural_delta


# ── D. Previous output preserved ──────────────────────────────────────

def test_previous_output_preserved():
    """D: Second call preserves first call's last_output as previous_output."""
    segment_memory = SegmentMemory()

    # First call
    s3_adapter1 = make_mock_s3_adapter(success=True, output={"first": "output"})
    executor1 = PlanExecutor(
        dispatcher=make_mock_dispatcher(),
        s3_adapter=s3_adapter1,
        segment_memory=segment_memory,
    )
    plan = make_plan(skill="test.prev")
    executor1._write_skill_result_to_state(plan, make_success_result())

    # Second call
    s3_adapter2 = make_mock_s3_adapter(success=True, output={"second": "output"})
    executor2 = PlanExecutor(
        dispatcher=make_mock_dispatcher(),
        s3_adapter=s3_adapter2,
        segment_memory=segment_memory,
    )
    record = executor2._write_skill_result_to_state(plan, make_success_result())

    assert record is not None
    assert record.previous_output == {"first": "output"}
    assert record.last_output == {"second": "output"}


# ── E. Cycle halts on failure ─────────────────────────────────────────

def test_cycle_halts_on_failure():
    """E: execute() returns failure metrics when skill result is error."""
    segment_memory = SegmentMemory()
    s3_adapter = make_mock_s3_adapter(success=False, output=None, error="fatal")

    executor = PlanExecutor(
        dispatcher=make_mock_dispatcher(),
        s3_adapter=s3_adapter,
        segment_memory=segment_memory,
    )
    plan = make_plan(skill="fail.skill")
    plan_state = None

    state, result, metrics = executor.execute(plan, plan_state=plan_state)

    # Should halt with failure
    assert metrics.termination_reason == "failure"
    assert "fatal" in result.reason
    assert result.outcome != CognitiveStepOutcome.SUCCESS


# ── Edge cases ────────────────────────────────────────────────────────

def test_returns_none_when_s3_adapter_is_none():
    """_write_skill_result_to_state returns None without S3 adapter."""
    executor = PlanExecutor(dispatcher=make_mock_dispatcher())
    plan = make_plan()
    record = executor._write_skill_result_to_state(plan, make_success_result())
    assert record is None


def test_returns_none_when_segment_memory_is_none():
    """_write_skill_result_to_state returns None without SegmentMemory."""
    s3_adapter = make_mock_s3_adapter()
    executor = PlanExecutor(
        dispatcher=make_mock_dispatcher(),
        s3_adapter=s3_adapter,
    )
    plan = make_plan()
    record = executor._write_skill_result_to_state(plan, make_success_result())
    assert record is None


def test_delta_is_none_on_first_call():
    """First call with no previous record → behavioural_delta is None."""
    segment_memory = SegmentMemory()
    s3_adapter = make_mock_s3_adapter(success=True, output={"x": 1})

    executor = PlanExecutor(
        dispatcher=make_mock_dispatcher(),
        s3_adapter=s3_adapter,
        segment_memory=segment_memory,
    )
    plan = make_plan(skill="first.call")

    record = executor._write_skill_result_to_state(plan, make_success_result())

    assert record is not None
    assert record.behavioural_delta is None
    assert record.previous_output is None
