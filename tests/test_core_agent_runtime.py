from unittest.mock import MagicMock, patch

from src.core.agent.config import AgentConfig
from src.core.agent.runtime import AgentRuntime
from src.core.llm.types import CoreLLMResponse
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
    transport.call.return_value = CoreLLMResponse(text="hello")
    runtime = AgentRuntime(transport=transport, config=_make_config())

    result = runtime.step("say hi")

    assert result.text == "hello"
    assert result.is_text is True
    transport.call.assert_called_once()


@patch("src.core.agent.runtime.execute_tool")
@patch("src.core.agent.runtime.select_tool")
def test_step_executes_selected_tool(mock_select_tool, mock_execute_tool):
    transport = MagicMock()
    transport.call.return_value = CoreLLMResponse(
        tool_name="echo",
        tool_args={"text": "hello"},
    )
    runtime = AgentRuntime(transport=transport, config=_make_config())

    spec = MagicMock()
    mock_select_tool.return_value = spec
    mock_execute_tool.return_value = CoreResult.from_tool("echo", {"text": "hello"})

    result = runtime.step("echo hello")

    assert result.tool_name == "echo"
    assert result.tool_output == {"text": "hello"}
    assert mock_select_tool.called
    select_kwargs = mock_select_tool.call_args.kwargs
    assert select_kwargs["tool_name"] == "echo"
    assert select_kwargs["allowed_tools"] == ["echo", "add"]
    assert select_kwargs["allowed_categories"] == [SkillCategory.GENERAL, SkillCategory.MATH]
    assert select_kwargs["allowed_side_effects"] == [SideEffect.NONE, SideEffect.READ]
    assert hasattr(select_kwargs["registry"], "get_spec")
    mock_execute_tool.assert_called_once_with(spec, {"text": "hello"})


def test_run_returns_text_immediately_when_no_tool_requested():
    transport = MagicMock()
    transport.call.return_value = CoreLLMResponse(text="done")
    runtime = AgentRuntime(transport=transport, config=_make_config(max_steps=3))

    result = runtime.run("start")

    assert result.text == "done"
    assert transport.call.call_count == 1


@patch("src.core.agent.runtime.execute_tool")
@patch("src.core.agent.runtime.select_tool")
def test_run_returns_tool_error_and_stops(mock_select_tool, mock_execute_tool):
    transport = MagicMock()
    transport.call.return_value = CoreLLMResponse(tool_name="echo", tool_args={"text": "hello"})
    runtime = AgentRuntime(transport=transport, config=_make_config(max_steps=5))

    mock_select_tool.return_value = MagicMock()
    mock_execute_tool.return_value = CoreResult.from_error(RuntimeError("tool failed"))

    result = runtime.run("start")

    assert result.is_error is True
    assert result.error == "tool failed"
    assert transport.call.call_count == 1


@patch("src.core.agent.runtime.execute_tool")
@patch("src.core.agent.runtime.select_tool")
def test_run_returns_last_tool_result_at_max_steps(mock_select_tool, mock_execute_tool):
    transport = MagicMock()
    transport.call.return_value = CoreLLMResponse(tool_name="echo", tool_args={"text": "hello"})
    runtime = AgentRuntime(transport=transport, config=_make_config(max_steps=2))

    mock_select_tool.return_value = MagicMock()
    mock_execute_tool.side_effect = [
        CoreResult.from_tool("echo", "first"),
        CoreResult.from_tool("echo", "second"),
    ]

    result = runtime.run("start")

    assert result.tool_name == "echo"
    assert result.tool_output == "second"
    assert transport.call.call_count == 2


@patch("src.core.agent.runtime.execute_tool")
@patch("src.core.agent.runtime.select_tool")
def test_run_appends_tool_output_to_followup_prompt(mock_select_tool, mock_execute_tool):
    transport = MagicMock()
    transport.call.side_effect = [
        CoreLLMResponse(tool_name="echo", tool_args={"text": "hello"}),
        CoreLLMResponse(text="complete"),
    ]
    runtime = AgentRuntime(transport=transport, config=_make_config(max_steps=2))

    mock_select_tool.return_value = MagicMock()
    mock_execute_tool.return_value = CoreResult.from_tool("echo", {"text": "hello"})

    result = runtime.run("start")

    assert result.text == "complete"
    first_prompt = transport.call.call_args_list[0].kwargs["prompt"]
    second_prompt = transport.call.call_args_list[1].kwargs["prompt"]
    assert first_prompt == "start"
    assert "Tool echo returned: {'text': 'hello'}" in second_prompt
