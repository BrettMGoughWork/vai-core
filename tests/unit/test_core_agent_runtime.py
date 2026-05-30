from unittest.mock import MagicMock, patch
import time

from src.core.state.config import AgentConfig, LoopPolicyConfig
from src.core.state.core_step_executor import CoreStepExecutor
from src.core.state.step_outcome import StepOutcome
from src.core.state.runtime import AgentRuntime, _result_summary
from src.core.llm.types import CoreLLMResponse
from src.primitives.runtime.categories import SkillCategory
from src.primitives.runtime.side_effects import SideEffect
from src.core.types.result import CoreResult
from src.execution.degraded_mode import DegradedModeController
from src.execution.retry.circuit_breaker import CircuitBreaker
from src.execution.safe_failure import SafeFailure
from src.execution.self_healing import SelfHealingController
from concurrent.futures import TimeoutError


def _make_config(max_steps: int = 4) -> AgentConfig:
    return AgentConfig(
        model="test-model",
        allowed_tools=["echo", "add"],
        allowed_categories=[SkillCategory.GENERAL, SkillCategory.MATH],
        allowed_side_effects=[SideEffect.NONE, SideEffect.READ],
        max_steps=max_steps,
    )


def test_agent_config_defaults_max_steps():
    config = AgentConfig(
        model="test-model",
        allowed_tools=["echo"],
        allowed_categories=[SkillCategory.GENERAL],
        allowed_side_effects=[SideEffect.NONE],
    )

    assert config.max_steps == 4


def test_step_returns_text_when_no_tool_requested():
    transport = MagicMock()
    runtime = AgentRuntime(transport=transport, config=_make_config())

    expected = CoreResult.from_text("hello")
    with patch("src.core.state.runtime.core_step", return_value=(expected, MagicMock(), StepOutcome.SUCCESS)) as mock_core_step:
        result = runtime.step("say hi")

    assert result == expected
    args = mock_core_step.call_args.args
    assert args[1] is transport
    assert args[2] == runtime.config


def test_run_returns_on_success_outcome():
    transport = MagicMock()
    runtime = AgentRuntime(transport=transport, config=_make_config(max_steps=3))

    expected = CoreResult.from_text("done")
    with patch(
        "src.core.state.runtime.core_step",
        side_effect=[(expected, MagicMock(), StepOutcome.SUCCESS)],
    ) as mock_core_step:
        result = runtime.run("start")

    assert result == expected
    assert mock_core_step.call_count == 1


def test_run_returns_on_fatal_outcome():
    transport = MagicMock()
    runtime = AgentRuntime(transport=transport, config=_make_config(max_steps=3))

    expected = CoreResult.from_error(RuntimeError("boom"))
    with patch(
        "src.core.state.runtime.core_step",
        side_effect=[(expected, MagicMock(), StepOutcome.FATAL)],
    ) as mock_core_step:
        result = runtime.run("start")

    assert result == expected
    assert mock_core_step.call_count == 1


def test_run_continues_on_recoverable_and_returns_later_success():
    transport = MagicMock()
    runtime = AgentRuntime(transport=transport, config=_make_config(max_steps=3))

    tool_result = CoreResult.from_tool("echo", "ok")
    final_result = CoreResult.from_text("complete")
    with patch(
        "src.core.state.runtime.core_step",
        side_effect=[
            (tool_result, MagicMock(), StepOutcome.RECOVERABLE),
            (final_result, MagicMock(), StepOutcome.SUCCESS),
        ],
    ) as mock_core_step:
        result = runtime.run("start")

    assert result == final_result
    assert mock_core_step.call_count == 2


def test_run_returns_last_result_after_max_steps_for_noop():
    transport = MagicMock()
    runtime = AgentRuntime(transport=transport, config=_make_config(max_steps=2))

    step1 = CoreResult.from_tool("echo", None)
    step2 = CoreResult.from_tool("echo", None)
    with patch(
        "src.core.state.runtime.core_step",
        side_effect=[
            (step1, MagicMock(), StepOutcome.NOOP),
            (step2, MagicMock(), StepOutcome.NOOP),
        ],
    ):
        result = runtime.run("start")

    assert result == step2


def test_run_handles_step_timeout():
    transport = MagicMock()
    
    loop_policy = LoopPolicyConfig(per_step_timeout=0.1)
    config = AgentConfig(
        model="test-model",
        allowed_tools=["echo"],
        allowed_categories=[SkillCategory.GENERAL],
        allowed_side_effects=[SideEffect.NONE],
        loop_policy=loop_policy,
    )
    runtime = AgentRuntime(transport=transport, config=config)

    step1_result = CoreResult.from_tool("echo", "ok")
    
    def slow_core_step(*args, **kwargs):
        time.sleep(0.5)
        return (step1_result, MagicMock(), StepOutcome.RECOVERABLE)

    with patch("src.core.state.runtime.core_step", side_effect=slow_core_step):
        result = runtime.run("start")

    assert result is not None
    assert result.is_error is True


def test_run_handles_wall_time_timeout():
    transport = MagicMock()
    
    loop_policy = LoopPolicyConfig(max_wall_time=0.2)
    config = AgentConfig(
        model="test-model",
        allowed_tools=["echo"],
        allowed_categories=[SkillCategory.GENERAL],
        allowed_side_effects=[SideEffect.NONE],
        max_steps=10,
        loop_policy=loop_policy,
    )
    runtime = AgentRuntime(transport=transport, config=config)

    step_result = CoreResult.from_tool("echo", "ok")
    
    def slow_core_step(*args, **kwargs):
        time.sleep(0.15)
        return (step_result, MagicMock(), StepOutcome.RECOVERABLE)

    with patch("src.core.state.runtime.core_step", side_effect=slow_core_step):
        result = runtime.run("start")

    assert result is not None
    assert result.is_error is True


def test_run_self_heal_clears_real_state_and_returns_safe_failure():
    transport = MagicMock()
    runtime = AgentRuntime(transport=transport, config=_make_config(max_steps=3))
    executor = CoreStepExecutor(
        llm_client=MagicMock(),
        config=runtime.config,
    )
    captured_state = {}

    def trigger_self_heal(state, _transport, _config):
        captured_state["state"] = state
        state.append_llm("stale")
        state.last_result = CoreResult.from_text("old")
        state.last_error = "old-error"
        state.step_count = 3
        state.metadata["job_id"] = "job-1"
        state.trace.append(MagicMock())
        executor.self_healing.failure_count = executor.self_healing.failure_threshold
        return executor.run(state)

    with patch("src.core.state.runtime.core_step", side_effect=trigger_self_heal):
        result = runtime.run("start")

    state = captured_state["state"]
    assert isinstance(result, SafeFailure)
    assert result.metadata.get("self_healed") is True
    assert state.input == "start"
    assert state.history == []
    assert state.last_result is None
    assert state.last_error is None
    assert state.step_count == 1
    assert state.metadata == {}
    assert len(state.trace) == 1


def test_run_safe_failure_is_stable_and_summary_is_ui_safe():
    transport = MagicMock()
    runtime = AgentRuntime(transport=transport, config=_make_config(max_steps=3))
    safe_failure = SafeFailure(
        error_type="ToolError",
        message="Poison job detected",
        metadata={"job_id": "job-123", "poison_job": True},
    )

    with patch(
        "src.core.state.runtime.core_step",
        return_value=(safe_failure, MagicMock(), StepOutcome.FATAL),
    ):
        result = runtime.run("start")

    assert _result_summary(safe_failure) == "ToolError: Poison job detected"
    assert isinstance(result, SafeFailure)
    assert result.error_type == "ToolError"
    assert result.message == "Poison job detected"
    assert result.metadata == {"job_id": "job-123", "poison_job": True}


def test_runtime_sequential_safety_path_remains_stable():
    class ScriptedLLM:
        def __init__(self, actions):
            self.actions = list(actions)
            self.call_count = 0

        def call(self, **kwargs):
            self.call_count += 1
            action = self.actions.pop(0)
            if isinstance(action, Exception):
                raise action
            return action

    transport = MagicMock()
    runtime = AgentRuntime(transport=transport, config=_make_config(max_steps=1))
    scripted_llm = ScriptedLLM(
        [
            TimeoutError(),  # run1 retry attempt 1
            CoreLLMResponse(text="retry-ok"),  # run1 retry attempt 2
            CoreLLMResponse(tool_name="echo", tool_args={}),  # run2 (opens breaker via error result)
            CoreLLMResponse(tool_name="echo", tool_args={}),  # run3 (circuit breaker safe failure)
            RuntimeError("llm-down"),  # run4 retry attempt 1
            RuntimeError("llm-down"),  # run4 retry attempt 2 -> safe failure + degraded active
            CoreLLMResponse(tool_name="echo", tool_args={}),  # run5 (degraded mode safe failure)
            RuntimeError("llm-down"),  # run6 retry attempt 1
            RuntimeError("llm-down"),  # run6 retry attempt 2 -> self-heal threshold reached
        ]
    )
    spec = MagicMock()
    spec.name = "echo"
    spec.is_idempotent = True
    spec.run.return_value = CoreResult.from_error(RuntimeError("tool failed"))

    executor = CoreStepExecutor(
        llm_client=scripted_llm,
        config=runtime.config,
        circuit_breaker=CircuitBreaker(failure_threshold=1, cooldown=60.0),
        degraded_mode=DegradedModeController(threshold=2),
        self_healing=SelfHealingController(failure_threshold=3),
    )

    def delegated_core_step(state, _transport, _config):
        return executor.run(state)

    with patch("src.core.state.runtime.core_step", side_effect=delegated_core_step), patch(
        "src.core.state.core_step_executor.SkillRegistry.all_specs_for_agent", return_value=[spec]
    ), patch("src.core.state.core_step_executor.select_tool", return_value=spec):
        r1 = runtime.run("phase-retry")
        r2 = runtime.run("phase-breaker-open")
        r3 = runtime.run("phase-breaker-block")
        r4 = runtime.run("phase-degraded-trigger")
        r5 = runtime.run("phase-degraded-active")
        r6 = runtime.run("phase-self-heal-arm")
        r7 = runtime.run("phase-self-heal-fire")

    assert isinstance(r1, CoreResult) and r1.text == "retry-ok"
    assert isinstance(r2, CoreResult) and r2.is_error
    assert isinstance(r3, SafeFailure) and r3.metadata.get("tool") == "echo"
    assert isinstance(r4, SafeFailure) and r4.metadata.get("panic") is True
    assert isinstance(r5, SafeFailure) and r5.metadata.get("degraded_mode") is True
    assert isinstance(r6, SafeFailure) and r6.metadata.get("panic") is True
    assert isinstance(r7, SafeFailure) and r7.metadata.get("self_healed") is True
