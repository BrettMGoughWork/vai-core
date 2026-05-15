from unittest.mock import MagicMock, patch

from src.core.agent.config import AgentConfig
from src.core.agent.outcome import StepOutcome
from src.core.agent.runtime import AgentRuntime
from src.core.skills.categories import SkillCategory
from src.core.skills.side_effects import SideEffect
from src.core.types.result import CoreResult


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
    with patch("src.core.agent.runtime.core_step", return_value=(expected, MagicMock(), StepOutcome.SUCCESS)) as mock_core_step:
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
        "src.core.agent.runtime.core_step",
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
        "src.core.agent.runtime.core_step",
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
        "src.core.agent.runtime.core_step",
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
        "src.core.agent.runtime.core_step",
        side_effect=[
            (step1, MagicMock(), StepOutcome.NOOP),
            (step2, MagicMock(), StepOutcome.NOOP),
        ],
    ):
        result = runtime.run("start")

    assert result == step2
