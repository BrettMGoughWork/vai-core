"""
Tests for AtomicityEnforcer.
=============================

Covers:
- record_outcome with SubtaskOutcome enum
- is_plan_failed / all_succeeded query methods
- finalise with all-succeeded / failed results
- Compensation callback on failure
- Edge cases: no records, mixed outcomes, no compensations
"""

from __future__ import annotations

import pytest

from src.agent.decomposition.atomicity import (
    AtomicityEnforcer,
    PlanExecutionResult,
    SubtaskOutcome,
)

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _make_enforcer(plan_id: str = "plan-1") -> AtomicityEnforcer:
    return AtomicityEnforcer(plan_id=plan_id)


# ══════════════════════════════════════════════════════════════════════════════
# record_outcome
# ══════════════════════════════════════════════════════════════════════════════


class TestRecordOutcome:
    def test_record_success(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS, result={"output": "ok"})
        assert enforcer._outcomes["a"] == SubtaskOutcome.SUCCESS
        assert enforcer._results["a"] == {"output": "ok"}

    def test_record_permanent_failure(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.PERMANENT_FAILURE)
        assert enforcer._outcomes["a"] == SubtaskOutcome.PERMANENT_FAILURE

    def test_record_retryable_failure(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.RETRYABLE_FAILURE)
        assert enforcer._outcomes["a"] == SubtaskOutcome.RETRYABLE_FAILURE

    def test_record_timeout(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.TIMEOUT)
        assert enforcer._outcomes["a"] == SubtaskOutcome.TIMEOUT

    def test_record_cancelled(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.CANCELLED)
        assert enforcer._outcomes["a"] == SubtaskOutcome.CANCELLED

    def test_record_all_success(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        enforcer.record_outcome("b", SubtaskOutcome.SUCCESS)
        assert len(enforcer._outcomes) == 2
        assert enforcer._outcomes["a"] == SubtaskOutcome.SUCCESS
        assert enforcer._outcomes["b"] == SubtaskOutcome.SUCCESS

    def test_record_overwrites_previous(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.PERMANENT_FAILURE)
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        assert enforcer._outcomes["a"] == SubtaskOutcome.SUCCESS


# ══════════════════════════════════════════════════════════════════════════════
# Query methods
# ══════════════════════════════════════════════════════════════════════════════


class TestQueryMethods:
    def test_is_plan_failed_no_records(self) -> None:
        assert not _make_enforcer().is_plan_failed()

    def test_is_plan_failed_with_permanent_failure(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.PERMANENT_FAILURE)
        assert enforcer.is_plan_failed()

    def test_is_plan_failed_with_timeout(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.TIMEOUT)
        assert enforcer.is_plan_failed()

    def test_is_plan_failed_not_with_retryable(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.RETRYABLE_FAILURE)
        assert not enforcer.is_plan_failed()

    def test_is_plan_failed_not_with_cancelled(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.CANCELLED)
        assert not enforcer.is_plan_failed()

    def test_is_plan_failed_not_with_success(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        assert not enforcer.is_plan_failed()

    def test_all_succeeded_true(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        assert enforcer.all_succeeded()

    def test_all_succeeded_false_with_permanent_failure(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.PERMANENT_FAILURE)
        assert not enforcer.all_succeeded()

    def test_all_succeeded_false_not_all_success(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        enforcer.record_outcome("b", SubtaskOutcome.RETRYABLE_FAILURE)
        assert not enforcer.all_succeeded()

    def test_all_succeeded_false_on_empty(self) -> None:
        assert not _make_enforcer().all_succeeded()

    def test_all_succeeded_true_multiple(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        enforcer.record_outcome("b", SubtaskOutcome.SUCCESS)
        assert enforcer.all_succeeded()


# ══════════════════════════════════════════════════════════════════════════════
# finalise
# ══════════════════════════════════════════════════════════════════════════════


class TestFinalise:
    def test_all_successful(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        enforcer.record_outcome("b", SubtaskOutcome.SUCCESS)
        result = enforcer.finalise(merged_output="merged result")
        assert result.all_succeeded is True
        assert result.merged_output == "merged result"
        assert result.plan_id == "plan-1"

    def test_permanent_failure(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        enforcer.record_outcome("b", SubtaskOutcome.PERMANENT_FAILURE)
        result = enforcer.finalise()
        assert result.all_succeeded is False
        assert result.failure_reason is not None
        assert "b" in result.failure_reason

    def test_timeout_is_failure(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.TIMEOUT)
        result = enforcer.finalise()
        assert result.all_succeeded is False

    def test_no_records_returns_not_succeeded(self) -> None:
        result = _make_enforcer().finalise()
        assert result.all_succeeded is False

    def test_mixed_with_retryable_not_final(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        enforcer.record_outcome("b", SubtaskOutcome.RETRYABLE_FAILURE)
        result = enforcer.finalise()
        assert result.all_succeeded is False
        assert result.failure_reason is not None

    def test_mixed_with_cancelled_not_final(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        enforcer.record_outcome("b", SubtaskOutcome.CANCELLED)
        result = enforcer.finalise()
        assert result.all_succeeded is False

    def test_outcomes_in_result(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        enforcer.record_outcome("b", SubtaskOutcome.PERMANENT_FAILURE)
        result = enforcer.finalise()
        assert result.subtask_outcomes["a"] == SubtaskOutcome.SUCCESS
        assert result.subtask_outcomes["b"] == SubtaskOutcome.PERMANENT_FAILURE


# ══════════════════════════════════════════════════════════════════════════════
# Compensation callbacks
# ══════════════════════════════════════════════════════════════════════════════


class TestCompensations:
    def test_compensation_called_on_failure_for_successful(self) -> None:
        calls: list[tuple[str, dict]] = []

        def compensate(subtask_id: str, result: dict) -> None:
            calls.append((subtask_id, result))

        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS, result={"output": "ok"})
        enforcer.record_outcome("b", SubtaskOutcome.PERMANENT_FAILURE)
        enforcer.finalise(compensation_fn=compensate)

        assert len(calls) == 1
        assert calls[0][0] == "a"
        assert calls[0][1] == {"output": "ok"}

    def test_no_compensation_on_full_success(self) -> None:
        calls: list[str] = []

        def compensate(subtask_id: str, result: dict) -> None:
            calls.append(subtask_id)

        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        enforcer.finalise(merged_output="all good", compensation_fn=compensate)
        assert calls == []

    def test_no_compensation_on_all_failed(self) -> None:
        """No successes to compensate when everything failed."""
        calls: list[str] = []

        def compensate(subtask_id: str, result: dict) -> None:
            calls.append(subtask_id)

        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.PERMANENT_FAILURE)
        enforcer.record_outcome("b", SubtaskOutcome.PERMANENT_FAILURE)
        enforcer.finalise(compensation_fn=compensate)
        assert calls == []

    def test_no_compensation_when_no_fn_provided(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        enforcer.record_outcome("b", SubtaskOutcome.PERMANENT_FAILURE)
        result = enforcer.finalise()
        assert result.all_succeeded is False

    def test_compensation_executed_tracked_in_result(self) -> None:
        def compensate(subtask_id: str, result: dict) -> None:
            pass

        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS, result={"output": "ok"})
        enforcer.record_outcome("b", SubtaskOutcome.PERMANENT_FAILURE)
        result = enforcer.finalise(compensation_fn=compensate)
        assert "a" in result.compensations_executed

    def test_build_failure_reason(self) -> None:
        enforcer = _make_enforcer()
        enforcer.record_outcome("a", SubtaskOutcome.SUCCESS)
        enforcer.record_outcome("b", SubtaskOutcome.PERMANENT_FAILURE)
        enforcer.record_outcome("c", SubtaskOutcome.TIMEOUT)
        reason = enforcer._build_failure_reason()
        assert "b: permanent_failure" in reason
        assert "c: timeout" in reason
        assert "a:" not in reason
