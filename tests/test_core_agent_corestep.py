from unittest.mock import MagicMock, patch

from src.core.agent.config import AgentConfig
from src.core.agent.corestep import core_step
from src.core.agent.state import ConversationState
from src.core.llm.types import CoreLLMResponse
from src.core.skills.categories import SkillCategory
from src.core.skills.side_effects import SideEffect
from src.core.types.result import CoreResult


def _make_config() -> AgentConfig:
    return AgentConfig(
        model="test-model",
        allowed_tools=["echo"],
        allowed_categories=[SkillCategory.GENERAL],
        allowed_side_effects=[SideEffect.NONE],
        max_steps=1,
    )


@patch("src.core.agent.corestep.SkillRegistry.all_specs_for_agent")
def test_core_step_returns_text_and_updates_state(mock_all_specs_for_agent):
    mock_all_specs_for_agent.return_value = []
    transport = MagicMock()
    transport.call.return_value = CoreLLMResponse(text="done")
    state = ConversationState(input="start")

    result, new_state = core_step(state=state, transport=transport, config=_make_config())

    assert result.text == "done"
    assert new_state.last_result == result
    assert new_state.history == ["LLM: done"]
    call_kwargs = transport.call.call_args.kwargs
    assert call_kwargs["prompt"] == "User: start"
    assert call_kwargs["tools"] == []


@patch("src.core.agent.corestep.execute_tool")
@patch("src.core.agent.corestep.select_tool")
@patch("src.core.agent.corestep.SkillRegistry.all_specs_for_agent")
def test_core_step_executes_tool_and_appends_tool_history(
    mock_all_specs_for_agent, mock_select_tool, mock_execute_tool
):
    mock_all_specs_for_agent.return_value = [MagicMock()]
    transport = MagicMock()
    transport.call.return_value = CoreLLMResponse(tool_name="echo", tool_args={"text": "hi"})

    spec = MagicMock()
    spec.name = "echo"
    mock_select_tool.return_value = spec
    mock_execute_tool.return_value = CoreResult.from_tool("echo", "ok")
    state = ConversationState(input="start")

    result, new_state = core_step(state=state, transport=transport, config=_make_config())

    assert result.tool_name == "echo"
    assert result.tool_output == "ok"
    assert new_state.last_result == result
    assert new_state.history == ["TOOL echo: ok"]
    mock_execute_tool.assert_called_once_with(spec, {"text": "hi"})


@patch("src.core.agent.corestep.execute_tool")
@patch("src.core.agent.corestep.select_tool")
@patch("src.core.agent.corestep.SkillRegistry.all_specs_for_agent")
def test_core_step_appends_error_history_when_tool_fails(
    mock_all_specs_for_agent, mock_select_tool, mock_execute_tool
):
    mock_all_specs_for_agent.return_value = [MagicMock()]
    transport = MagicMock()
    transport.call.return_value = CoreLLMResponse(tool_name="echo", tool_args={"text": "hi"})

    spec = MagicMock()
    spec.name = "echo"
    mock_select_tool.return_value = spec
    mock_execute_tool.return_value = CoreResult.from_error(RuntimeError("boom"))
    state = ConversationState(input="start")

    result, new_state = core_step(state=state, transport=transport, config=_make_config())

    assert result.is_error is True
    assert result.error == "boom"
    assert new_state.last_result == result
    assert new_state.history == ["TOOL echo ERROR: boom"]
