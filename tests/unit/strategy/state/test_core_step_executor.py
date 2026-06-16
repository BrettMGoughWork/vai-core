"""
Tests for src.strategy.state.core_step_executor — CoreStepExecutor, classify_step, isdone.

Focus: deterministic outcome routing, correct StepOutcome branching, safety
substrate behaviour (self-healing, poison detection, circuit breaker, degraded mode).
Architecture boundary: only imports from domain, utility, and execution strata.
"""
import pytest
from unittest.mock import patch

from src.strategy.state.core_step_executor import CoreStepExecutor
from src.strategy.state.step_outcome import StepOutcome, classify_step
from src.strategy.state.isdone import isdone
from src.strategy.state.config import AgentConfig, LoopPolicyConfig
from src.strategy.state.state import ConversationState
from src.runtime.llm.types import CoreLLMResponse
from src.strategy.types.result import CoreResult
from src.runtime.safe_failure import SafeFailure
from src.runtime.retry.circuit_breaker import CircuitBreaker
from src.runtime.degraded_mode import DegradedModeController
from src.runtime.self_healing import SelfHealingController
from src.runtime.poison_job_detector import PoisonJobDetector
from src.strategy.types.capabilities import SkillCategory, SideEffect


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeLLM:
    """Scripted LLM — pops responses from a queue, never touches the network."""

    def __init__(self, responses):
        self._queue = list(responses)
        self.calls = []

    def call(self, prompt, tools, model, temperature=0.2):
        self.calls.append({"prompt": prompt, "tools": tools, "model": model})
        resp = self._queue.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class FakeTool:
    """Scripted tool — returns a fixed CoreResult synchronously."""

    def __init__(self, name, result):
        self.name = name
        self._result = result
        self.is_idempotent = True

    def run(self, **kwargs):
        return self._result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(max_steps=4):
    return AgentConfig(
        model="test-model",
        allowed_tools=["echo"],
        allowed_categories=[SkillCategory.GENERAL],
        allowed_side_effects=[SideEffect.NONE],
        max_steps=max_steps,
        loop_policy=LoopPolicyConfig(max_steps=max_steps),
    )


def _executor(llm, **overrides):
    return CoreStepExecutor(llm_client=llm, config=_config(), **overrides)


def _state(prompt="hello"):
    return ConversationState(input=prompt)


@pytest.fixture
def no_skills():
    """Patch SkillRegistry so the executor sees an empty tool list."""
    with patch("src.strategy.state.core_step_executor.SkillRegistry.all_specs_for_agent", return_value=[]):
        yield


# ── classify_step ─────────────────────────────────────────────────────────────

class TestClassifyStep:
    def test_error_result_yields_fatal(self):
        assert classify_step(CoreResult.from_error(RuntimeError("x"))) == StepOutcome.FATAL

    def test_text_result_yields_success(self):
        assert classify_step(CoreResult.from_text("hi")) == StepOutcome.SUCCESS

    def test_tool_result_with_output_yields_recoverable(self):
        assert classify_step(CoreResult.from_tool("echo", "ok")) == StepOutcome.RECOVERABLE

    def test_tool_result_with_none_output_yields_noop(self):
        assert classify_step(CoreResult.from_tool("echo", None)) == StepOutcome.NOOP

    def test_empty_result_yields_noop(self):
        assert classify_step(CoreResult()) == StepOutcome.NOOP


# ── isdone ────────────────────────────────────────────────────────────────────

class TestIsDone:
    def _state_at(self, step_count):
        s = ConversationState()
        s.step_count = step_count
        return s

    def test_success_outcome_is_done(self):
        assert isdone(self._state_at(0), StepOutcome.SUCCESS, _config(max_steps=10)) is True

    def test_fatal_outcome_is_done(self):
        assert isdone(self._state_at(0), StepOutcome.FATAL, _config(max_steps=10)) is True

    def test_recoverable_outcome_is_not_done(self):
        assert isdone(self._state_at(0), StepOutcome.RECOVERABLE, _config(max_steps=10)) is False

    def test_noop_outcome_is_not_done(self):
        assert isdone(self._state_at(0), StepOutcome.NOOP, _config(max_steps=10)) is False

    def test_max_steps_reached_is_done(self):
        assert isdone(self._state_at(4), StepOutcome.NOOP, _config(max_steps=4)) is True

    def test_below_max_steps_is_not_done(self):
        assert isdone(self._state_at(3), StepOutcome.NOOP, _config(max_steps=4)) is False

    def test_step_count_zero_with_noop_is_not_done(self):
        assert isdone(self._state_at(0), StepOutcome.NOOP, _config(max_steps=4)) is False


# ── CoreStepExecutor — text path ──────────────────────────────────────────────

class TestCoreStepExecutorTextPath:
    def test_text_response_yields_success_outcome(self, no_skills):
        llm = FakeLLM([CoreLLMResponse(text="hello")])

        _, _, outcome = _executor(llm).run(_state())

        assert outcome == StepOutcome.SUCCESS

    def test_text_response_returns_core_result_with_text(self, no_skills):
        llm = FakeLLM([CoreLLMResponse(text="the answer")])

        result, _, _ = _executor(llm).run(_state())

        assert isinstance(result, CoreResult)
        assert result.text == "the answer"

    def test_text_response_appends_to_llm_history(self, no_skills):
        llm = FakeLLM([CoreLLMResponse(text="recorded")])
        state = _state()

        _executor(llm).run(state)

        assert "recorded" in state.llm_history

    def test_empty_text_response_is_valid(self, no_skills):
        llm = FakeLLM([CoreLLMResponse(text="")])

        result, _, outcome = _executor(llm).run(_state())

        assert outcome == StepOutcome.SUCCESS
        assert result.text == ""

    def test_llm_called_once_per_run(self, no_skills):
        llm = FakeLLM([CoreLLMResponse(text="ok")])

        _executor(llm).run(_state())

        assert len(llm.calls) == 1

    def test_prompt_passed_to_llm(self, no_skills):
        llm = FakeLLM([CoreLLMResponse(text="ok")])

        _executor(llm).run(_state("my-prompt"))

        assert "my-prompt" in llm.calls[0]["prompt"]


# ── CoreStepExecutor — tool path ──────────────────────────────────────────────

class TestCoreStepExecutorToolPath:
    def _patched_tool_run(self, tool_result):
        """Returns context managers to fake skill registry + select + execute."""
        return (
            patch("src.strategy.state.core_step_executor.SkillRegistry.all_specs_for_agent", return_value=[]),
            patch("src.strategy.state.core_step_executor.select_tool", return_value=FakeTool("echo", tool_result)),
            patch("src.strategy.state.core_step_executor.execute_with_retry", return_value=tool_result),
        )

    def test_tool_with_output_yields_recoverable(self):
        llm = FakeLLM([CoreLLMResponse(tool_name="echo", tool_args={})])
        tool_result = CoreResult.from_tool("echo", "output")
        p1, p2, p3 = self._patched_tool_run(tool_result)

        with p1, p2, p3:
            result, _, outcome = _executor(llm).run(_state())

        assert outcome == StepOutcome.RECOVERABLE
        assert result.tool_name == "echo"

    def test_tool_with_none_output_yields_noop(self):
        llm = FakeLLM([CoreLLMResponse(tool_name="echo", tool_args={})])
        tool_result = CoreResult.from_tool("echo", None)
        p1, p2, p3 = self._patched_tool_run(tool_result)

        with p1, p2, p3:
            _, _, outcome = _executor(llm).run(_state())

        assert outcome == StepOutcome.NOOP

    def test_tool_error_result_yields_fatal(self):
        llm = FakeLLM([CoreLLMResponse(tool_name="echo", tool_args={})])
        tool_result = CoreResult.from_error(RuntimeError("tool broke"))
        p1, p2, p3 = self._patched_tool_run(tool_result)

        with p1, p2, p3:
            result, _, outcome = _executor(llm).run(_state())

        assert outcome == StepOutcome.FATAL
        assert result.is_error

    def test_successful_tool_appends_to_tool_history(self):
        llm = FakeLLM([CoreLLMResponse(tool_name="echo", tool_args={})])
        tool_result = CoreResult.from_tool("echo", "out")
        p1, p2, p3 = self._patched_tool_run(tool_result)
        state = _state()

        with p1, p2, p3:
            _executor(llm).run(state)

        assert any(name == "echo" for name, _ in state.tool_history)


# ── CoreStepExecutor — LLM failure ────────────────────────────────────────────

class TestCoreStepExecutorLLMFailure:
    def test_llm_exception_returns_safe_failure(self, no_skills):
        llm = FakeLLM([RuntimeError("network down")])

        result, _, outcome = _executor(llm).run(_state())

        assert isinstance(result, SafeFailure)
        assert outcome == StepOutcome.FATAL

    def test_llm_exception_sets_panic_flag(self, no_skills):
        llm = FakeLLM([RuntimeError("timeout")])

        result, _, _ = _executor(llm).run(_state())

        assert result.metadata.get("panic") is True

    def test_llm_exception_message_preserved(self, no_skills):
        # SystemError retry policy allows 1 retry — seed 2 copies to exhaust retries
        # so call_with_retry re-raises the original RuntimeError (not an IndexError).
        llm = FakeLLM([RuntimeError("connection refused"), RuntimeError("connection refused")])

        result, _, _ = _executor(llm).run(_state())

        assert "connection refused" in result.message


# ── CoreStepExecutor — self-healing ───────────────────────────────────────────

class TestSelfHealing:
    def test_heal_triggers_at_threshold(self, no_skills):
        healer = SelfHealingController(failure_threshold=2)
        healer.record_failure()
        healer.record_failure()  # at threshold
        llm = FakeLLM([])  # should not be called

        result, _, outcome = _executor(llm, self_healing=healer).run(_state())

        assert isinstance(result, SafeFailure)
        assert result.metadata.get("self_healed") is True
        assert outcome == StepOutcome.FATAL

    def test_heal_resets_state(self, no_skills):
        healer = SelfHealingController(failure_threshold=1)
        healer.record_failure()
        llm = FakeLLM([])
        state = _state("original")
        state.step_count = 7
        state.history.append("stale-entry")

        _executor(llm, self_healing=healer).run(state)

        assert state.step_count == 0
        assert state.history == []

    def test_heal_does_not_trigger_below_threshold(self, no_skills):
        healer = SelfHealingController(failure_threshold=3)
        healer.record_failure()  # 1 of 3 — safe
        llm = FakeLLM([CoreLLMResponse(text="still running")])

        result, _, outcome = _executor(llm, self_healing=healer).run(_state())

        assert outcome == StepOutcome.SUCCESS
        assert not isinstance(result, SafeFailure)

    def test_success_resets_failure_count(self, no_skills):
        healer = SelfHealingController(failure_threshold=3)
        healer.record_failure()
        healer.record_failure()
        llm = FakeLLM([CoreLLMResponse(text="ok")])

        _executor(llm, self_healing=healer).run(_state())

        assert healer.failure_count == 0


# ── CoreStepExecutor — poison job ─────────────────────────────────────────────

class TestPoisonJobDetection:
    def test_poisoned_job_returns_safe_failure(self, no_skills):
        detector = PoisonJobDetector(failure_threshold=1)
        detector.record_failure("bad-job")  # threshold=1 → poisoned
        llm = FakeLLM([])
        state = _state("bad-job")
        state.metadata["job_id"] = "bad-job"

        result, _, outcome = _executor(llm, poison_job_detector=detector).run(state)

        assert isinstance(result, SafeFailure)
        assert result.metadata.get("poison_job") is True
        assert outcome == StepOutcome.FATAL

    def test_clean_job_proceeds_normally(self, no_skills):
        detector = PoisonJobDetector(failure_threshold=5)
        llm = FakeLLM([CoreLLMResponse(text="clean")])

        result, _, outcome = _executor(llm, poison_job_detector=detector).run(_state("fresh"))

        assert outcome == StepOutcome.SUCCESS
        assert not isinstance(result, SafeFailure)

    def test_job_below_threshold_is_not_poisoned(self, no_skills):
        detector = PoisonJobDetector(failure_threshold=3)
        detector.record_failure("marginal")
        detector.record_failure("marginal")  # 2 of 3 — not yet poisoned
        llm = FakeLLM([CoreLLMResponse(text="ok")])
        state = _state("marginal")
        state.metadata["job_id"] = "marginal"

        _, _, outcome = _executor(llm, poison_job_detector=detector).run(state)

        assert outcome == StepOutcome.SUCCESS


# ── CoreStepExecutor — circuit breaker ───────────────────────────────────────

class TestCircuitBreaker:
    def test_open_circuit_blocks_tool_and_returns_safe_failure(self):
        breaker = CircuitBreaker(failure_threshold=1, cooldown=60.0)
        breaker.record_failure("echo")  # opens circuit
        llm = FakeLLM([CoreLLMResponse(tool_name="echo", tool_args={})])
        tool = FakeTool("echo", CoreResult.from_tool("echo", "out"))

        with patch("src.strategy.state.core_step_executor.SkillRegistry.all_specs_for_agent", return_value=[]), \
             patch("src.strategy.state.core_step_executor.select_tool", return_value=tool):
            result, _, outcome = _executor(llm, circuit_breaker=breaker).run(_state())

        assert isinstance(result, SafeFailure)
        assert result.metadata.get("tool") == "echo"
        assert outcome == StepOutcome.FATAL

    def test_closed_circuit_does_not_interfere_with_text_response(self, no_skills):
        breaker = CircuitBreaker(failure_threshold=3, cooldown=5.0)
        llm = FakeLLM([CoreLLMResponse(text="all good")])

        result, _, outcome = _executor(llm, circuit_breaker=breaker).run(_state())

        assert outcome == StepOutcome.SUCCESS
        assert not isinstance(result, SafeFailure)


# ── CoreStepExecutor — degraded mode ─────────────────────────────────────────

class TestDegradedMode:
    def test_tool_request_in_degraded_mode_blocked(self):
        degraded = DegradedModeController(threshold=1)
        degraded.record_failure()  # activates
        llm = FakeLLM([CoreLLMResponse(tool_name="echo", tool_args={})])

        with patch("src.strategy.state.core_step_executor.SkillRegistry.all_specs_for_agent", return_value=[]):
            result, _, outcome = _executor(llm, degraded_mode=degraded).run(_state())

        assert isinstance(result, SafeFailure)
        assert result.metadata.get("degraded_mode") is True
        assert outcome == StepOutcome.FATAL

    def test_text_response_works_in_degraded_mode(self, no_skills):
        degraded = DegradedModeController(threshold=1)
        degraded.record_failure()
        llm = FakeLLM([CoreLLMResponse(text="degraded but alive")])

        result, _, outcome = _executor(llm, degraded_mode=degraded).run(_state())

        assert outcome == StepOutcome.SUCCESS
        assert result.text == "degraded but alive"

    def test_degraded_mode_activates_after_threshold(self):
        degraded = DegradedModeController(threshold=2)
        assert not degraded.is_active()
        degraded.record_failure()
        assert not degraded.is_active()
        degraded.record_failure()
        assert degraded.is_active()

    def test_degraded_mode_stays_active_after_success(self):
        degraded = DegradedModeController(threshold=1)
        degraded.record_failure()
        degraded.record_success()  # does not reset when active

        assert degraded.is_active()