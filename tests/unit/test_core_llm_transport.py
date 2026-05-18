from unittest.mock import MagicMock

from src.core.llm.transport import LLMTransport
from src.core.llm.types import CoreLLMResponse
from src.skills.toolspec import ToolSpec


def test_transport_converts_toolspec_to_schema():
    spec = ToolSpec(
        name="add",
        description="Add two numbers",
        schema={"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
        handler=lambda a, b: a + b,
    )

    transport = LLMTransport(MagicMock())
    converted = transport._convert_tool_spec(spec)

    assert converted["type"] == "function"
    assert converted["function"]["name"] == "add"
    assert converted["function"]["description"] == "Add two numbers"
    assert "parameters" in converted["function"]


def test_transport_parses_tool_call_response_from_provider_dict():
    transport = LLMTransport(MagicMock())
    raw = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "add",
                                "arguments": '{"a": 5, "b": 3}',
                            }
                        }
                    ]
                }
            }
        ]
    }

    result = transport._parse_response(raw)

    assert isinstance(result, CoreLLMResponse)
    assert result.tool_name == "add"
    assert result.tool_args == {"a": 5, "b": 3}
    assert result.text is None


def test_transport_parses_text_response_from_provider_dict():
    transport = LLMTransport(MagicMock())
    raw = {
        "choices": [
            {
                "message": {
                    "tool_calls": None,
                    "content": "I cannot help with that.",
                }
            }
        ]
    }

    result = transport._parse_response(raw)

    assert isinstance(result, CoreLLMResponse)
    assert result.text == "I cannot help with that."
    assert result.tool_name is None
    assert result.tool_args is None


def test_transport_call_invokes_provider_chat():
    mock_client = MagicMock()
    mock_client.chat.return_value = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "echo",
                                "arguments": '{"text": "hello"}',
                            }
                        }
                    ]
                }
            }
        ]
    }
    transport = LLMTransport(mock_client)

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

    mock_client.chat.assert_called_once()
    call_kwargs = mock_client.chat.call_args.kwargs
    assert call_kwargs["model"] == "test-model"
    assert call_kwargs["temperature"] == 0.5
    assert len(call_kwargs["tools"]) == 1

    assert result.tool_name == "echo"
    assert result.tool_args == {"text": "hello"}
