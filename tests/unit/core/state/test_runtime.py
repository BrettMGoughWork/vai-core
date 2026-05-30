"""
Tests for src.core.state.runtime — AgentRuntime loop and _result_summary.

Focus: deterministic loop outcomes, correct branching on StepOutcome, loop
termination conditions (SUCCESS, FATAL, max_steps, wall time, per-step timeout).
Architecture boundary: no cross-stratum imports beyond what runtime itself uses.
"""
import pytest
from unittest.mock import MagicMock, patch
from concurrent.futures import TimeoutError as FutureTimeoutError

from src.core.state.runtime import AgentRuntime, _result_summary
from src.core.state.config import AgentConfig, LoopPolicyConfig
from src.core.state.step_outcome import StepOutcome
from src.core.state.state import ConversationState
from src.core.types.result import CoreResult
from src.execution.safe_failure import SafeFailure
from src.primitives.runtime.categories import SkillCategory
from src.primitives.runtime.side_effects import SideEffect


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(max_steps=4, per_step_timeout=None, max_wall_time=None):
    return AgentConfig(
        model="test-model",
        allowed_tools=[],
        allowed_categories=[SkillCategory.GENERAL],
        allowed_side_effects=[SideEffect.NONE],
        max_steps=max_steps,
        loop_policy=LoopPolicyConfig(
            per_step_timeout=per_step_timeout,
            max_wall_time=max_wall_time,
        ),
    )


def _runtime(max_steps=4, per_step_timeout=None, max_wall_time=None):
    return AgentRuntime(transport=MagicMock(), config=_config(max_steps, per_step_timeout, max_wall_time))


def _step_result(outcome: StepOutcome, result: CoreResult):
    """Returns a scripted core_step return value."""
    state = ConversationState()
    return result, state, outcome


def _scripted_core_step(responses):
    """Returns a side_effect list for patching core_step; each entry is (result, state, outcome)."""
    return responses


# ── _result_summary ───────────────────────────────────────────────────────────

class TestResultSummary:
    def test_none_returns_empty_string(self):
        assert _result_summary(None) == ""

    def test_safe_failure_returns_type_and_message(self):
        sf = SafeFailure(message="oops", error_type="RuntimeError", metadata={})
        summary = _result_summary(sf)
        assert "RuntimeError" in summary
        assert "oops" in summary

    def test_error_result_returns_error_string(self):
        result = CoreResult.from_error(RuntimeError("something failed"))
        assert _result_summary(result) == "something failed"

    def test_text_result_returns_text(self):
        result = CoreResult.from_text("agent response")
        assert _result_summary(result) == "agent response"

    def test_tool_result_returns_name_and_output(self):
        result = CoreResult.from_tool("calculator", "42")
        summary = _result_summary(result)
        assert "calculator" in summary
        assert "42" in summary

    def test_empty_result_returns_empty_string(self):
        assert _result_summary(CoreResult()) == ""

    def test_error_with_none_error_field_returns_empty(self):
        result = CoreResult(error=None)
        assert _result_summary(result) == ""


# ── AgentRuntime.step ─────────────────────────────────────────────────────────

class TestAgentRuntimeStep:
    def test_step_returns_core_result(self):
        runtime = _runtime()
        expected = CoreResult.from_text("done")

        with patch("src.core.state.runtime.core_step", return_value=(expected, ConversationState(), StepOutcome.SUCCESS)):
            result = runtime.step("prompt")

        assert result is expected

    def test_step_calls_core_step_once(self):
        runtime = _runtime()

        with patch("src.core.state.runtime.core_step", return_value=(CoreResult.from_text("ok"), ConversationState(), StepOutcome.SUCCESS)) as mock_cs:
            runtime.step("prompt")

        mock_cs.assert_called_once()

    def test_step_passes_prompt_to_state(self):
        runtime = _runtime()
        captured = {}

        def capture(state, transport, config):
            captured["input"] = state.input
            return CoreResult.from_text("ok"), state, StepOutcome.SUCCESS

        with patch("src.core.state.runtime.core_step", side_effect=capture):
            runtime.step("my-prompt")

        assert captured["input"] == "my-prompt"


# ── AgentRuntime.run — termination on SUCCESS ─────────────────────────────────

class TestAgentRuntimeRunSuccess:
    def test_success_on_first_step_returns_text_result(self):
        runtime = _runtime(max_steps=4)
        expected = CoreResult.from_text("final answer")

        with patch("src.core.state.runtime.core_step", return_value=(expected, ConversationState(), StepOutcome.SUCCESS)):
            result = runtime.run("prompt")

        assert result.text == "final answer"
        assert not result.is_error

    def test_success_exits_after_one_step(self):
        runtime = _runtime(max_steps=4)
        call_count = {"n": 0}

        def scripted(state, transport, config):
            call_count["n"] += 1
            return CoreResult.from_text("done"), state, StepOutcome.SUCCESS

        with patch("src.core.state.runtime.core_step", side_effect=scripted):
            runtime.run("prompt")

        assert call_count["n"] == 1

    def test_recoverable_then_success_runs_two_steps(self):
        runtime = _runtime(max_steps=4)
        responses = [
            (CoreResult.from_tool("echo", "partial"), ConversationState(), StepOutcome.RECOVERABLE),
            (CoreResult.from_text("final"), ConversationState(), StepOutcome.SUCCESS),
        ]
        call_count = {"n": 0}

        def scripted(state, transport, config):
            r = responses[call_count["n"]]
            call_count["n"] += 1
            return r

        with patch("src.core.state.runtime.core_step", side_effect=scripted):
            result = runtime.run("prompt")

        assert call_count["n"] == 2
        assert result.text == "final"


# ── AgentRuntime.run — termination on FATAL ───────────────────────────────────

class TestAgentRuntimeRunFatal:
    def test_fatal_on_first_step_exits_immediately(self):
        runtime = _runtime(max_steps=4)
        call_count = {"n": 0}

        def scripted(state, transport, config):
            call_count["n"] += 1
            return CoreResult.from_error(RuntimeError("fatal error")), state, StepOutcome.FATAL

        with patch("src.core.state.runtime.core_step", side_effect=scripted):
            result = runtime.run("prompt")

        assert call_count["n"] == 1
        assert result.is_error

    def test_fatal_result_preserves_error_message(self):
        runtime = _runtime(max_steps=4)

        with patch("src.core.state.runtime.core_step", return_value=(CoreResult.from_error(RuntimeError("broken")), ConversationState(), StepOutcome.FATAL)):
            result = runtime.run("prompt")

        assert "broken" in result.error


# ── AgentRuntime.run — max_steps exhaustion ───────────────────────────────────

class TestAgentRuntimeRunMaxSteps:
    def test_noop_loop_exhausts_max_steps_returns_last_result(self):
        runtime = _runtime(max_steps=2)

        def noop_step(state, transport, config):
            return CoreResult.from_tool("echo", None), state, StepOutcome.NOOP

        with patch("src.core.state.runtime.core_step", side_effect=noop_step):
            result = runtime.run("prompt")

        # Runtime returns the last result as-is; it's a NOOP tool result, not an error
        assert isinstance(result, CoreResult)
        assert result.is_tool
        assert not result.is_error

    def test_zero_max_steps_returns_max_steps_error(self):
        # With max_steps=0, isdone is True immediately — loop never runs, result is None
        runtime = _runtime(max_steps=0)

        result = runtime.run("prompt")

        assert result.is_error
        assert "max_steps" in result.error.lower()

    def test_noop_loop_runs_exactly_max_steps(self):
        runtime = _runtime(max_steps=3)
        call_count = {"n": 0}

        def noop_step(state, transport, config):
            call_count["n"] += 1
            return CoreResult.from_tool("echo", None), state, StepOutcome.NOOP

        with patch("src.core.state.runtime.core_step", side_effect=noop_step):
            runtime.run("prompt")

        assert call_count["n"] == 3

    def test_recoverable_loop_exhausted_returns_last_result(self):
        runtime = _runtime(max_steps=2)

        def recoverable_step(state, transport, config):
            return CoreResult.from_tool("echo", "partial"), state, StepOutcome.RECOVERABLE

        with patch("src.core.state.runtime.core_step", side_effect=recoverable_step):
            result = runtime.run("prompt")

        # Same as NOOP: runtime returns the last result, not a synthesized error
        assert isinstance(result, CoreResult)
        assert result.tool_output == "partial"
        assert not result.is_error


# ── AgentRuntime.run — SafeFailure propagation ────────────────────────────────

class TestAgentRuntimeRunSafeFailure:
    def test_safe_failure_returned_directly(self):
        runtime = _runtime(max_steps=4)
        sf = SafeFailure(message="panic", error_type="RuntimeError", metadata={"panic": True})

        with patch("src.core.state.runtime.core_step", return_value=(sf, ConversationState(), StepOutcome.FATAL)):
            result = runtime.run("prompt")

        assert isinstance(result, SafeFailure)
        assert result.message == "panic"

    def test_safe_failure_is_not_wrapped_in_core_result(self):
        runtime = _runtime(max_steps=4)
        sf = SafeFailure(message="abort", error_type="PoisonJob", metadata={})

        with patch("src.core.state.runtime.core_step", return_value=(sf, ConversationState(), StepOutcome.FATAL)):
            result = runtime.run("prompt")

        assert type(result) is SafeFailure

    def test_safe_failure_stops_loop_immediately(self):
        runtime = _runtime(max_steps=4)
        call_count = {"n": 0}
        sf = SafeFailure(message="stop", error_type="CircuitBreaker", metadata={})

        def scripted(state, transport, config):
            call_count["n"] += 1
            return sf, state, StepOutcome.FATAL

        with patch("src.core.state.runtime.core_step", side_effect=scripted):
            runtime.run("prompt")

        assert call_count["n"] == 1


# ── AgentRuntime.run — per-step timeout ──────────────────────────────────────

class TestAgentRuntimeRunPerStepTimeout:
    def _make_timeout_mock(self):
        """Returns a mock ThreadPoolExecutor whose future raises FutureTimeoutError."""
        mock_future = MagicMock()
        mock_future.result.side_effect = FutureTimeoutError()

        mock_exec = MagicMock()
        mock_exec.__enter__.return_value = mock_exec
        mock_exec.__exit__.return_value = False
        mock_exec.submit.return_value = mock_future

        return mock_exec

    def test_timeout_returns_error_result(self):
        runtime = _runtime(per_step_timeout=0.001)
        mock_exec = self._make_timeout_mock()

        with patch("src.core.state.runtime.ThreadPoolExecutor", return_value=mock_exec):
            result = runtime.run("prompt")

        assert isinstance(result, CoreResult)
        assert result.is_error

    def test_timeout_error_message_mentions_timeout(self):
        runtime = _runtime(per_step_timeout=0.001)
        mock_exec = self._make_timeout_mock()

        with patch("src.core.state.runtime.ThreadPoolExecutor", return_value=mock_exec):
            result = runtime.run("prompt")

        assert "timed out" in result.error.lower()

    def test_timeout_stops_loop_after_one_attempt(self):
        runtime = _runtime(max_steps=4, per_step_timeout=0.001)
        submit_count = {"n": 0}
        mock_future = MagicMock()
        mock_future.result.side_effect = FutureTimeoutError()

        mock_exec = MagicMock()
        mock_exec.__enter__.return_value = mock_exec
        mock_exec.__exit__.return_value = False

        def counted_submit(*args, **kwargs):
            submit_count["n"] += 1
            return mock_future

        mock_exec.submit.side_effect = counted_submit

        with patch("src.core.state.runtime.ThreadPoolExecutor", return_value=mock_exec):
            runtime.run("prompt")

        assert submit_count["n"] == 1


# ── AgentRuntime.run — wall time exceeded ────────────────────────────────────

class TestAgentRuntimeRunWallTime:
    def test_wall_time_exceeded_returns_error(self):
        runtime = _runtime(max_wall_time=0.5)

        with patch("src.core.state.runtime.time") as mock_time:
            mock_time.monotonic.side_effect = [0.0, 1000.0]
            result = runtime.run("prompt")

        assert result.is_error

    def test_wall_time_error_message_mentions_wall_time(self):
        runtime = _runtime(max_wall_time=0.5)

        with patch("src.core.state.runtime.time") as mock_time:
            mock_time.monotonic.side_effect = [0.0, 1000.0]
            result = runtime.run("prompt")

        assert "wall time" in result.error.lower()

    def test_wall_time_stops_before_running_any_step(self):
        runtime = _runtime(max_steps=4, max_wall_time=0.5)
        call_count = {"n": 0}

        def scripted(state, transport, config):
            call_count["n"] += 1
            return CoreResult.from_text("done"), state, StepOutcome.SUCCESS

        with patch("src.core.state.runtime.time") as mock_time, \
             patch("src.core.state.runtime.core_step", side_effect=scripted):
            mock_time.monotonic.side_effect = [0.0, 1000.0]
            runtime.run("prompt")

        assert call_count["n"] == 0  # wall time check fires before step runs
