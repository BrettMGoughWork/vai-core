import pytest
from unittest.mock import MagicMock, patch

from src.execution.engine import execute_tool
from src.core.types.result import CoreResult
from src.capabilities.primitives.base import PrimitiveBase


def test_execute_tool_returns_core_result_on_success():
    """execute_tool returns CoreResult with tool name and output."""
    mock_skill = MagicMock()
    mock_skill.output_schema = None
    mock_skill.name = "test_skill"
    mock_skill.output_schema = None
    mock_skill.run.return_value = 42

    result = execute_tool(mock_skill, {"a": 1, "b": 2}, drift_memory=MagicMock(), subgoal_id="sg1", segment_id="seg1", step_id="step1")

    assert isinstance(result, CoreResult)
    assert result.tool_name == "test_skill"
    assert result.tool_output == 42
    assert result.error is None
    assert result.is_tool is True
    assert result.is_error is False


def test_execute_tool_calls_skill_run_with_args():
    """execute_tool passes all arguments to skill.run()."""
    mock_skill = MagicMock()
    mock_skill.output_schema = None
    mock_skill.name = "add"
    mock_skill.run.return_value = 100

    execute_tool(mock_skill, {"a": 50, "b": 50}, drift_memory=MagicMock(), subgoal_id="sg1", segment_id="seg1", step_id="step1")

    mock_skill.run.assert_called_once_with(a=50, b=50)


def test_execute_tool_returns_error_result_on_exception():
    """execute_tool returns CoreResult with error message on exception."""
    mock_skill = MagicMock()
    mock_skill.output_schema = None
    mock_skill.name = "failing_skill"
    mock_skill.run.side_effect = ValueError("Invalid input")

    result = execute_tool(mock_skill, {"x": "bad"}, drift_memory=MagicMock(), subgoal_id="sg1", segment_id="seg1", step_id="step1")

    assert isinstance(result, CoreResult)
    assert result.is_error is True
    assert "failing_skill" in result.error
    assert "Invalid input" in result.error
    assert result.tool_name is None
    assert result.tool_output is None


def test_execute_tool_error_includes_skill_name():
    """Error result message includes the skill name."""
    mock_skill = MagicMock()
    mock_skill.output_schema = None
    mock_skill.name = "my_special_skill"
    mock_skill.run.side_effect = RuntimeError("Something broke")

    result = execute_tool(mock_skill, {}, drift_memory=MagicMock(), subgoal_id="sg1", segment_id="seg1", step_id="step1")

    assert "my_special_skill" in result.error


def test_execute_tool_preserves_handler_result_type():
    """execute_tool preserves the exact result type from handler."""
    mock_skill = MagicMock()
    mock_skill.output_schema = None
    mock_skill.name = "dict_skill"
    expected_output = {"sum": 42, "count": 2}
    mock_skill.run.return_value = expected_output

    result = execute_tool(mock_skill, {}, drift_memory=MagicMock(), subgoal_id="sg1", segment_id="seg1", step_id="step1")

    assert result.tool_output == expected_output
    assert result.tool_output is expected_output


def test_execute_tool_with_empty_args():
    """execute_tool works with no arguments."""
    mock_skill = MagicMock()
    mock_skill.output_schema = None
    mock_skill.name = "no_args"
    mock_skill.run.return_value = "done"

    result = execute_tool(mock_skill, {}, drift_memory=MagicMock(), subgoal_id="sg1", segment_id="seg1", step_id="step1")

    assert isinstance(result, CoreResult)
    assert result.tool_name == "no_args"
    assert result.tool_output == "done"
    mock_skill.run.assert_called_once_with()


def test_execute_tool_with_multiple_args():
    """execute_tool passes all arguments correctly."""
    mock_skill = MagicMock()
    mock_skill.output_schema = None
    mock_skill.name = "multi"
    mock_skill.run.return_value = "result"

    result = execute_tool(mock_skill, {"a": 1, "b": "text", "c": [1, 2, 3]}, drift_memory=MagicMock(), subgoal_id="sg1", segment_id="seg1", step_id="step1")

    assert result.tool_output == "result"
    mock_skill.run.assert_called_once_with(a=1, b="text", c=[1, 2, 3])


def test_execute_tool_handles_validation_errors():
    """execute_tool catches and returns ValidationError as CoreResult."""
    from src.core.types.errors import ValidationError

    mock_skill = MagicMock()
    mock_skill.output_schema = None
    mock_skill.name = "validate_skill"
    mock_skill.run.side_effect = ValidationError("Missing required field: x")

    result = execute_tool(mock_skill, {}, drift_memory=MagicMock(), subgoal_id="sg1", segment_id="seg1", step_id="step1")

    assert isinstance(result, CoreResult)
    assert result.is_error is True
    assert "validate_skill" in result.error


def test_execute_tool_handles_canonicalisation_errors():
    """execute_tool catches and returns canonicalisation errors as CoreResult."""
    mock_skill = MagicMock()
    mock_skill.output_schema = None
    mock_skill.name = "canon_skill"
    mock_skill.run.side_effect = TypeError("Cannot coerce value to int")

    result = execute_tool(mock_skill, {"x": "not_a_number"}, drift_memory=MagicMock(), subgoal_id="sg1", segment_id="seg1", step_id="step1")

    assert isinstance(result, CoreResult)
    assert result.is_error is True
    assert "canon_skill" in result.error


def test_execute_tool_handles_generic_exceptions():
    """execute_tool wraps any exception as ToolExecutionError."""
    mock_skill = MagicMock()
    mock_skill.output_schema = None
    mock_skill.name = "error_skill"
    mock_skill.run.side_effect = Exception("Something unexpected")

    result = execute_tool(mock_skill, {}, drift_memory=MagicMock(), subgoal_id="sg1", segment_id="seg1", step_id="step1")

    assert isinstance(result, CoreResult)
    assert result.is_error is True
    assert "error_skill" in result.error
    assert "Something unexpected" in result.error


def test_execute_tool_returns_none_output_safely():
    """execute_tool correctly returns None as tool_output."""
    mock_skill = MagicMock()
    mock_skill.output_schema = None
    mock_skill.name = "void_skill"
    mock_skill.run.return_value = None

    result = execute_tool(mock_skill, {}, drift_memory=MagicMock(), subgoal_id="sg1", segment_id="seg1", step_id="step1")

    assert isinstance(result, CoreResult)
    assert result.tool_name == "void_skill"
    assert result.tool_output is None
    assert result.is_tool is True
    assert result.is_error is False


def test_execute_tool_result_is_always_core_result():
    """execute_tool always returns a CoreResult, never raises."""
    mock_skill = MagicMock()
    mock_skill.output_schema = None
    mock_skill.name = "always_fails"
    mock_skill.run.side_effect = Exception("Catastrophic failure")

    # This should never raise—should return CoreResult with error
    result = execute_tool(mock_skill, {}, drift_memory=MagicMock(), subgoal_id="sg1", segment_id="seg1", step_id="step1")

    assert isinstance(result, CoreResult)
    assert result.is_error is True
