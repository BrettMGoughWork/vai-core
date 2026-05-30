"""
Planning loop orchestration tests.

Covers:
- decide_termination(): all exit conditions and priority
- LoopMetrics: duration and to_dict()
- LoopController.run(): full loop execution with fake CoreStep
- LoopOrchestrator.run(): delegates to LoopController
"""
import pytest

from src.core.planning.orchestration.loop_termination import decide_termination
from src.core.planning.orchestration.loop_metrics import LoopMetrics
from src.core.planning.orchestration.loop_controller import LoopController
from src.core.planning.safety.loop_policy import LoopPolicy
from src.core.planning.orchestration.loop_orchestrator import LoopOrchestrator
from src.core.planning.models.step_state import StepState, StepStatus
from src.core.types.step_result import StepResult
from src.core.types.cognitive_step_outcome import CognitiveStepOutcome as StepOutcome


# ── Fakes ─────────────────────────────────────────────────────────────────────

def _state(step_id="s0", created_at=0, status=StepStatus.PENDING):
    return StepState(
        step_id=step_id,
        cognitive_input={},
        status=status,
        created_at=created_at,
    )


def _result(outcome: StepOutcome, reason="test"):
    return StepResult(outcome=outcome, reason=reason, payload={}, trace={})


class ScriptedCoreStep:
    """
    Returns a pre-scripted sequence of (state_increment, StepResult).
    Each call advances created_at by the given increment.
    """
    def __init__(self, outcomes: list):
        self._outcomes = list(outcomes)
        self._call = 0

    def run(self, state: StepState):
        outcome = self._outcomes[self._call]
        self._call += 1
        new_state = state.replace(
            created_at=state.created_at + 1,
            status=StepStatus.RUNNING,
        )
        return new_state, _result(outcome)


class AllowPolicy:
    def allows_continue(self, state, result, step_count):
        return True


class DenyPolicy:
    def allows_continue(self, state, result, step_count):
        return False


# ── decide_termination() ──────────────────────────────────────────────────────

class TestDecideTermination:
    def _call(self, outcome, step_count=1, max_steps=None, elapsed=0, max_duration=None, policy=True):
        return decide_termination(
            result=_result(outcome),
            step_count=step_count,
            max_steps=max_steps,
            elapsed=elapsed,
            max_duration=max_duration,
            policy_allows_continue=policy,
        )

    def test_success_terminates(self):
        d = self._call(StepOutcome.SUCCESS)
        assert d.should_terminate is True
        assert d.reason == "success"

    def test_failure_terminates(self):
        d = self._call(StepOutcome.FAILURE)
        assert d.should_terminate is True
        assert d.reason == "failure"

    def test_tool_needed_terminates(self):
        d = self._call(StepOutcome.TOOL_NEEDED)
        assert d.should_terminate is True
        assert d.reason == "tool_needed"

    def test_continue_with_no_limits_does_not_terminate(self):
        d = self._call(StepOutcome.CONTINUE)
        assert d.should_terminate is False
        assert d.reason == "continue"

    def test_continue_at_step_budget_terminates(self):
        d = self._call(StepOutcome.CONTINUE, step_count=5, max_steps=5)
        assert d.should_terminate is True
        assert d.reason == "step_budget_exceeded"

    def test_continue_below_step_budget_does_not_terminate(self):
        d = self._call(StepOutcome.CONTINUE, step_count=4, max_steps=5)
        assert d.should_terminate is False

    def test_continue_at_duration_budget_terminates(self):
        d = self._call(StepOutcome.CONTINUE, elapsed=10, max_duration=10)
        assert d.should_terminate is True
        assert d.reason == "duration_budget_exceeded"

    def test_continue_below_duration_budget_does_not_terminate(self):
        d = self._call(StepOutcome.CONTINUE, elapsed=9, max_duration=10)
        assert d.should_terminate is False

    def test_continue_policy_violation_terminates(self):
        d = self._call(StepOutcome.CONTINUE, policy=False)
        assert d.should_terminate is True
        assert d.reason == "policy_violation"

    def test_step_budget_checked_before_duration(self):
        # Both exceeded — step budget takes priority
        d = self._call(StepOutcome.CONTINUE, step_count=5, max_steps=5, elapsed=10, max_duration=10)
        assert d.reason == "step_budget_exceeded"

    def test_terminal_outcomes_ignore_budgets(self):
        # SUCCESS always terminates regardless of step/duration budgets
        d = self._call(StepOutcome.SUCCESS, step_count=1, max_steps=1, elapsed=0, max_duration=0)
        assert d.reason == "success"


# ── LoopMetrics ───────────────────────────────────────────────────────────────

class TestLoopMetrics:
    def test_duration_computed_from_timestamps(self):
        m = LoopMetrics(step_count=3, start_created_at=10, end_created_at=25)
        assert m.duration == 15

    def test_duration_zero_when_timestamps_none(self):
        m = LoopMetrics()
        assert m.duration == 0

    def test_duration_zero_when_start_none(self):
        m = LoopMetrics(end_created_at=10)
        assert m.duration == 0

    def test_to_dict_contains_all_keys(self):
        m = LoopMetrics(step_count=2, start_created_at=0, end_created_at=5, termination_reason="success")
        d = m.to_dict()
        assert d["step_count"] == 2
        assert d["duration"] == 5
        assert d["termination_reason"] == "success"
        assert "start_created_at" in d
        assert "end_created_at" in d
        assert "extra" in d

    def test_default_termination_reason(self):
        m = LoopMetrics()
        assert m.termination_reason == "not_terminated"


# ── LoopController.run() ──────────────────────────────────────────────────────

class TestLoopController:
    def _run(self, outcomes, max_steps=20, max_duration=None, policy=None):
        step = ScriptedCoreStep(outcomes)
        ctrl = LoopController(
            core_step=step,
            max_steps=max_steps,
            max_duration=max_duration,
            policy=policy,
        )
        return ctrl.run(_state())

    def test_success_on_first_step(self):
        state, result, metrics = self._run([StepOutcome.SUCCESS])
        assert result.outcome == StepOutcome.SUCCESS
        assert metrics.termination_reason == "success"
        assert metrics.step_count == 1

    def test_failure_on_first_step(self):
        _, result, metrics = self._run([StepOutcome.FAILURE])
        assert result.outcome == StepOutcome.FAILURE
        assert metrics.termination_reason == "failure"

    def test_tool_needed_on_first_step(self):
        _, result, metrics = self._run([StepOutcome.TOOL_NEEDED])
        assert result.outcome == StepOutcome.TOOL_NEEDED
        assert metrics.termination_reason == "tool_needed"

    def test_continues_then_succeeds(self):
        outcomes = [StepOutcome.CONTINUE, StepOutcome.CONTINUE, StepOutcome.SUCCESS]
        _, result, metrics = self._run(outcomes)
        assert result.outcome == StepOutcome.SUCCESS
        assert metrics.step_count == 3
        assert metrics.termination_reason == "success"

    def test_step_budget_exhaustion(self):
        # 5 CONTINUEs, budget of 3
        outcomes = [StepOutcome.CONTINUE] * 5
        _, result, metrics = self._run(outcomes, max_steps=3)
        assert metrics.termination_reason == "step_budget_exceeded"
        assert metrics.step_count == 3

    def test_duration_budget_exhaustion(self):
        # Each step advances created_at by 1; budget of 2 means terminate after 2 steps
        outcomes = [StepOutcome.CONTINUE] * 10
        _, result, metrics = self._run(outcomes, max_steps=100, max_duration=2)
        assert metrics.termination_reason == "duration_budget_exceeded"
        assert metrics.duration >= 2

    def test_policy_violation_terminates(self):
        outcomes = [StepOutcome.CONTINUE]
        _, result, metrics = self._run(outcomes, policy=DenyPolicy())
        assert metrics.termination_reason == "policy_violation"

    def test_policy_allow_does_not_block_continue(self):
        outcomes = [StepOutcome.CONTINUE, StepOutcome.SUCCESS]
        _, result, metrics = self._run(outcomes, policy=AllowPolicy())
        assert result.outcome == StepOutcome.SUCCESS

    def test_metrics_step_count_matches_steps_executed(self):
        outcomes = [StepOutcome.CONTINUE] * 4 + [StepOutcome.SUCCESS]
        _, _, metrics = self._run(outcomes)
        assert metrics.step_count == 5

    def test_metrics_duration_is_end_minus_start(self):
        outcomes = [StepOutcome.CONTINUE, StepOutcome.CONTINUE, StepOutcome.SUCCESS]
        initial = _state(created_at=10)
        step = ScriptedCoreStep(outcomes)
        ctrl = LoopController(core_step=step, max_steps=20)
        _, _, metrics = ctrl.run(initial)
        assert metrics.start_created_at == 10
        assert metrics.end_created_at == 13   # 10 + 3 steps
        assert metrics.duration == 3

    def test_last_result_is_final_step_result(self):
        outcomes = [StepOutcome.CONTINUE, StepOutcome.FAILURE]
        _, result, _ = self._run(outcomes)
        assert result.outcome == StepOutcome.FAILURE

    def test_metrics_extra_contains_last_step_hash(self):
        _, _, metrics = self._run([StepOutcome.SUCCESS])
        assert "last_step_hash" in metrics.extra
        assert isinstance(metrics.extra["last_step_hash"], str)

    def test_no_policy_is_treated_as_allow(self):
        outcomes = [StepOutcome.CONTINUE, StepOutcome.SUCCESS]
        _, result, _ = self._run(outcomes, policy=None)
        assert result.outcome == StepOutcome.SUCCESS


# ── LoopOrchestrator ──────────────────────────────────────────────────────────

class TestLoopOrchestrator:
    def test_delegates_to_controller_and_returns_same_result(self):
        step = ScriptedCoreStep([StepOutcome.CONTINUE, StepOutcome.SUCCESS])
        orch = LoopOrchestrator(
            core_step=step,
            max_steps=10,
            max_duration=100,
            policy=AllowPolicy(),
        )
        state, result, metrics = orch.run(_state())

        assert result.outcome == StepOutcome.SUCCESS
        assert metrics.step_count == 2
        assert metrics.termination_reason == "success"

    def test_step_budget_respected_by_orchestrator(self):
        step = ScriptedCoreStep([StepOutcome.CONTINUE] * 10)
        orch = LoopOrchestrator(
            core_step=step,
            max_steps=3,
            max_duration=1000,
            policy=AllowPolicy(),
        )
        _, _, metrics = orch.run(_state())

        assert metrics.termination_reason == "step_budget_exceeded"
        assert metrics.step_count == 3