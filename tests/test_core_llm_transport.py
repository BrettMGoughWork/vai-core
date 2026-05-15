import json
from unittest.mock import MagicMock, Mock

from src.core.llm.transport import LLMTransport
from src.core.llm.types import CoreLLMResponse
from src.core.skills.toolspec import ToolSpec


def test_transport_converts_toolspec_to_schema():
    """Transport converts ToolSpec objects to OpenAI tool schema."""
    spec = ToolSpec(
        name="add",
        description="Add two numbers",
        schema={"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
        handler=lambda a, b: a + b,
    )

    mock_client = MagicMock()
    transport = LLMTransport(mock_client)

    converted = transport._convert_tool_spec(spec)

    assert converted["type"] == "function"
    assert converted["function"]["name"] == "add"
    assert converted["function"]["description"] == "Add two numbers"
    assert "parameters" in converted["function"]


def test_transport_parses_tool_call_response():
    """Transport extracts tool name and args from LLM response."""
    mock_client = MagicMock()
    transport = LLMTransport(mock_client)

    # Mock an LLM response with a tool call
    mock_response = MagicMock()
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "add"
    mock_tool_call.function.arguments = '{"a": 5, "b": 3}'

    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.tool_calls = [mock_tool_call]

    result = transport._parse_response(mock_response)

    assert isinstance(result, CoreLLMResponse)
    assert result.tool_name == "add"
    assert result.tool_args == '{"a": 5, "b": 3}'
    assert result.text is None


def test_transport_parses_text_response():
    """Transport extracts text when LLM returns prose (no tool call)."""
    mock_client = MagicMock()
    transport = LLMTransport(mock_client)

    # Mock an LLM response with just text
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.tool_calls = None
    mock_response.choices[0].message.content = "I cannot help with that."

    result = transport._parse_response(mock_response)

    assert isinstance(result, CoreLLMResponse)
    assert result.text == "I cannot help with that."
    assert result.tool_name is None
    assert result.tool_args is None


def test_transport_call_invokes_client():
    """Transport.call() sends request to client and returns parsed response."""
    mock_client = MagicMock()
    transport = LLMTransport(mock_client)

    # Mock the client.chat.completions.create() call
    mock_response = MagicMock()
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "echo"
    mock_tool_call.function.arguments = '{"text": "hello"}'
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.tool_calls = [mock_tool_call]

    mock_client.chat.completions.create.return_value = mock_response

    spec = ToolSpec(
        name="echo",
        description="Echo text",
        schema={"type": "object", "properties": {"text": {"type": "string"}}},
        handler=lambda text: text,
    )

    result = transport.call(
        prompt="say hello",
        tools=[spec],
        model="test-model",
        temperature=0.5,
    )

    # Verify client was called
    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "test-model"
    assert call_kwargs["temperature"] == 0.5
    assert len(call_kwargs["tools"]) == 1

    # Verify response was parsed
    assert result.tool_name == "echo"
    assert result.tool_args == '{"text": "hello"}'
