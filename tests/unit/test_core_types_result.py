import pytest

from src.core.types.result import CoreResult
from src.execution.errors import ToolExecutionError


def test_core_result_from_text():
    """CoreResult.from_text() creates a text result."""
    result = CoreResult.from_text("Hello, world!")

    assert result.text == "Hello, world!"
    assert result.tool_name is None
    assert result.tool_output is None
    assert result.error is None


def test_core_result_from_tool():
    """CoreResult.from_tool() creates a tool execution result."""
    output = {"sum": 42, "count": 2}
    result = CoreResult.from_tool("add", output)

    assert result.tool_name == "add"
    assert result.tool_output == output
    assert result.text is None
    assert result.error is None


def test_core_result_from_error():
    """CoreResult.from_error() creates an error result with stringified exception."""
    exc = ValueError("Invalid input value")
    result = CoreResult.from_error(exc)

    assert result.error == "Invalid input value"
    assert result.text is None
    assert result.tool_name is None
    assert result.tool_output is None


def test_core_result_from_error_with_custom_exception():
    """CoreResult.from_error() works with custom exceptions."""
    exc = ToolExecutionError("Tool 'delete' failed: Permission denied")
    result = CoreResult.from_error(exc)

    assert result.error == "Tool 'delete' failed: Permission denied"
    assert result.is_error is True


def test_core_result_is_error_property():
    """is_error property returns True only when error is set."""
    error_result = CoreResult(error="Something went wrong")
    assert error_result.is_error is True

    text_result = CoreResult(text="Success")
    assert text_result.is_error is False

    tool_result = CoreResult(tool_name="echo", tool_output="hi")
    assert tool_result.is_error is False


def test_core_result_is_tool_property():
    """is_tool property returns True only when tool_name is set."""
    tool_result = CoreResult(tool_name="add", tool_output=5)
    assert tool_result.is_tool is True

    text_result = CoreResult(text="Hello")
    assert tool_result.is_tool is True
    assert text_result.is_tool is False

    error_result = CoreResult(error="Failed")
    assert error_result.is_tool is False


def test_core_result_is_text_property():
    """is_text property returns True only when text is set."""
    text_result = CoreResult(text="Hello")
    assert text_result.is_text is True

    tool_result = CoreResult(tool_name="echo", tool_output="hi")
    assert tool_result.is_text is False

    error_result = CoreResult(error="Failed")
    assert error_result.is_text is False


def test_core_result_multiple_fields_possible():
    """CoreResult can have text + tool fields (edge case, but technically allowed)."""
    result = CoreResult(text="Executed", tool_name="echo", tool_output="hello")

    assert result.is_text is True
    assert result.is_tool is True
    assert result.is_error is False


def test_core_result_all_none_valid():
    """CoreResult with all None fields is valid."""
    result = CoreResult()

    assert result.text is None
    assert result.tool_name is None
    assert result.tool_output is None
    assert result.error is None
    assert result.is_text is False
    assert result.is_tool is False
    assert result.is_error is False


def test_core_result_tool_output_any_type():
    """tool_output can be any type: dict, list, int, str, None, etc."""
    # Dict
    result1 = CoreResult.from_tool("skill1", {"key": "value"})
    assert result1.tool_output == {"key": "value"}

    # List
    result2 = CoreResult.from_tool("skill2", [1, 2, 3])
    assert result2.tool_output == [1, 2, 3]

    # Integer
    result3 = CoreResult.from_tool("skill3", 42)
    assert result3.tool_output == 42

    # String
    result4 = CoreResult.from_tool("skill4", "text")
    assert result4.tool_output == "text"

    # None
    result5 = CoreResult.from_tool("skill5", None)
    assert result5.tool_output is None


def test_core_result_error_stringifies_exception():
    """Error message is the string representation of the exception."""
    exc = RuntimeError("Detailed error message with context")
    result = CoreResult.from_error(exc)

    assert result.error == "Detailed error message with context"


def test_core_result_dataclass_fields():
    """CoreResult is a dataclass with expected fields."""
    result = CoreResult(text="test", tool_name="test_tool", tool_output=123, error=None)

    # Check that fields are accessible
    assert hasattr(result, "text")
    assert hasattr(result, "tool_name")
    assert hasattr(result, "tool_output")
    assert hasattr(result, "error")

    # Check repr works (dataclass feature)
    repr_str = repr(result)
    assert "CoreResult" in repr_str
    assert "text='test'" in repr_str
