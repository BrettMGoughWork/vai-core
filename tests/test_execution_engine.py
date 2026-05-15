import pytest
from unittest.mock import MagicMock, patch

from src.execution.engine import execute_tool
from src.execution.errors import ToolExecutionError
from src.core.skills.base import BaseSkill


def test_execute_tool_runs_skill_with_args():
    """execute_tool calls skill.run() with the provided arguments."""
    mock_skill = MagicMock(spec=BaseSkill)
    mock_skill.name = "test_skill"
    mock_skill.run.return_value = 42

    result = execute_tool(mock_skill, {"a": 1, "b": 2})

    assert result == 42
    mock_skill.run.assert_called_once_with(a=1, b=2)


def test_execute_tool_returns_handler_result():
    """execute_tool returns the exact result from the handler."""
    mock_skill = MagicMock(spec=BaseSkill)
    mock_skill.name = "add"
    expected_result = {"sum": 42, "count": 2}
    mock_skill.run.return_value = expected_result

    result = execute_tool(mock_skill, {"a": 10, "b": 32})

    assert result == expected_result
    assert result is expected_result


def test_execute_tool_raises_toolexecutionerror_on_failure():
    """execute_tool wraps any exception from skill.run() as ToolExecutionError."""
    mock_skill = MagicMock(spec=BaseSkill)
    mock_skill.name = "failing_skill"
    mock_skill.run.side_effect = ValueError("Invalid input")

    with pytest.raises(ToolExecutionError) as exc_info:
        execute_tool(mock_skill, {"x": "bad"})

    assert "failing_skill" in str(exc_info.value)
    assert "Invalid input" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_execute_tool_preserves_exception_chain():
    """ToolExecutionError preserves the original exception as __cause__."""
    mock_skill = MagicMock(spec=BaseSkill)
    mock_skill.name = "error_skill"
    original_error = RuntimeError("Original error")
    mock_skill.run.side_effect = original_error

    with pytest.raises(ToolExecutionError) as exc_info:
        execute_tool(mock_skill, {})

    assert exc_info.value.__cause__ is original_error


def test_execute_tool_with_empty_args():
    """execute_tool works with no arguments."""
    mock_skill = MagicMock(spec=BaseSkill)
    mock_skill.name = "no_args_skill"
    mock_skill.run.return_value = "done"

    result = execute_tool(mock_skill, {})

    assert result == "done"
    mock_skill.run.assert_called_once_with()


def test_execute_tool_with_multiple_args():
    """execute_tool passes all arguments to skill.run()."""
    mock_skill = MagicMock(spec=BaseSkill)
    mock_skill.name = "multi_arg_skill"
    mock_skill.run.return_value = "result"

    result = execute_tool(mock_skill, {"a": 1, "b": "text", "c": [1, 2, 3], "d": {"nested": True}})

    assert result == "result"
    mock_skill.run.assert_called_once_with(a=1, b="text", c=[1, 2, 3], d={"nested": True})


def test_execute_tool_handles_validation_errors():
    """execute_tool catches and wraps validation errors from skill.run()."""
    from src.core.skills.validator import ValidationError

    mock_skill = MagicMock(spec=BaseSkill)
    mock_skill.name = "validate_skill"
    mock_skill.run.side_effect = ValidationError("Missing required field: x")

    with pytest.raises(ToolExecutionError) as exc_info:
        execute_tool(mock_skill, {})

    assert "validate_skill" in str(exc_info.value)
    assert "Missing required field" in str(exc_info.value)


def test_execute_tool_handles_canonicalisation_errors():
    """execute_tool catches and wraps canonicalisation errors from skill.run()."""
    mock_skill = MagicMock(spec=BaseSkill)
    mock_skill.name = "canon_skill"
    mock_skill.run.side_effect = TypeError("Cannot coerce value to int")

    with pytest.raises(ToolExecutionError) as exc_info:
        execute_tool(mock_skill, {"x": "not_a_number"})

    assert "canon_skill" in str(exc_info.value)
    assert "Cannot coerce" in str(exc_info.value)


def test_execute_tool_error_message_includes_skill_name():
    """ToolExecutionError message always includes the skill name."""
    mock_skill = MagicMock(spec=BaseSkill)
    mock_skill.name = "my_special_skill"
    mock_skill.run.side_effect = Exception("Some error")

    with pytest.raises(ToolExecutionError) as exc_info:
        execute_tool(mock_skill, {})

    assert "my_special_skill" in str(exc_info.value)


def test_execute_tool_delegates_full_validation_to_skill():
    """execute_tool assumes skill.run() handles all validation and canonicalisation."""
    # This test documents that execute_tool is thin—it's the skill's responsibility
    # to validate and canonicalise before executing the handler.
    
    def fake_handler(a: int, b: int) -> int:
        return a + b

    mock_skill = MagicMock(spec=BaseSkill)
    mock_skill.name = "add"
    mock_skill.run = MagicMock(side_effect=lambda **kw: fake_handler(**kw))

    result = execute_tool(mock_skill, {"a": 5, "b": 3})

    assert result == 8
    # The skill's run method is called, trusting it to validate/canonicalise


def test_execute_tool_returns_none_when_handler_returns_none():
    """execute_tool correctly returns None if the handler returns None."""
    mock_skill = MagicMock(spec=BaseSkill)
    mock_skill.name = "void_skill"
    mock_skill.run.return_value = None

    result = execute_tool(mock_skill, {})

    assert result is None
