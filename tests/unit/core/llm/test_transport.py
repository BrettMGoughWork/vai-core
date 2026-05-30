"""
Additional contract tests for src.core.llm.transport.LLMTransport.

Supplements tests/unit/test_core_llm_transport.py with edge-case coverage:
tool args as pre-parsed dict, empty/absent tool_calls, messages format,
and no-tools call path.
"""
import json
from unittest.mock import MagicMock

from src.core.llm.transport import LLMTransport
from src.core.llm.types import CoreLLMResponse
from src.primitives.runtime.toolspec import ToolSpec


# ── Helpers ───────────────────────────────────────────────────────────────────

def _spec(name="echo", description="Echo text"):
    return ToolSpec(
        name=name,
        description=description,
        schema={"type": "object", "properties": {"text": {"type": "string"}}},
        handler=lambda text: text,
    )


def _raw_text(content="hello"):
    return {"choices": [{"message": {"tool_calls": None, "content": content}}]}


def _raw_tool(name, args):
    return {"choices": [{"message": {"tool_calls": [{"function": {"name": name, "arguments": args}}]}}]}


# ── _parse_response contract ───────────────────────────────────────────────────

class TestParseResponseContract:
    def test_tool_args_as_pre_parsed_dict(self):
        # Provider may return args already parsed (not a JSON string).
        transport = LLMTransport(MagicMock())
        raw = _raw_tool("add", {"a": 1, "b": 2})  # dict, not string

        result = transport._parse_response(raw)

        assert result.tool_name == "add"
        assert result.tool_args == {"a": 1, "b": 2}

    def test_tool_args_as_json_string(self):
        transport = LLMTransport(MagicMock())
        raw = _raw_tool("add", '{"a": 1, "b": 2}')  # JSON string

        result = transport._parse_response(raw)

        assert result.tool_args == {"a": 1, "b": 2}

    def test_empty_tool_calls_list_falls_through_to_text(self):
        transport = LLMTransport(MagicMock())
        raw = {"choices": [{"message": {"tool_calls": [], "content": "fallback"}}]}

        result = transport._parse_response(raw)

        assert result.text == "fallback"
        assert result.tool_name is None

    def test_no_tool_calls_key_returns_text(self):
        transport = LLMTransport(MagicMock())
        raw = {"choices": [{"message": {"content": "just text"}}]}

        result = transport._parse_response(raw)

        assert result.text == "just text"
        assert result.tool_name is None

    def test_text_result_has_no_tool_fields(self):
        transport = LLMTransport(MagicMock())
        result = transport._parse_response(_raw_text("response text"))

        assert result.tool_name is None
        assert result.tool_args is None

    def test_tool_result_has_no_text_field(self):
        transport = LLMTransport(MagicMock())
        result = transport._parse_response(_raw_tool("echo", '{"text": "hi"}'))

        assert result.text is None


# ── _convert_tool_spec contract ───────────────────────────────────────────────

class TestConvertToolSpecContract:
    def test_schema_passed_through_as_parameters(self):
        nested_schema = {
            "type": "object",
            "properties": {"url": {"type": "string"}, "timeout": {"type": "number"}},
            "required": ["url"],
        }
        spec = ToolSpec(name="fetch", description="Fetch URL", schema=nested_schema, handler=lambda url: url)
        transport = LLMTransport(MagicMock())

        converted = transport._convert_tool_spec(spec)

        assert converted["function"]["parameters"] == nested_schema

    def test_top_level_structure_is_function_type(self):
        transport = LLMTransport(MagicMock())
        converted = transport._convert_tool_spec(_spec())

        assert set(converted.keys()) == {"type", "function"}
        assert converted["type"] == "function"

    def test_function_block_has_required_keys(self):
        transport = LLMTransport(MagicMock())
        converted = transport._convert_tool_spec(_spec())

        assert {"name", "description", "parameters"} <= set(converted["function"].keys())


# ── call() messages format ────────────────────────────────────────────────────

class TestCallContract:
    def test_prompt_sent_as_single_user_message(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = _raw_text("ok")
        transport = LLMTransport(mock_client)

        transport.call(prompt="do something", tools=[], model="test-model")

        messages = mock_client.chat.call_args.kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "do something"

    def test_empty_tools_list_sends_empty_tool_defs(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = _raw_text("ok")
        transport = LLMTransport(mock_client)

        transport.call(prompt="hi", tools=[], model="test-model")

        sent_tools = mock_client.chat.call_args.kwargs["tools"]
        assert sent_tools == []

    def test_multiple_tools_all_converted(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = _raw_text("ok")
        transport = LLMTransport(mock_client)
        specs = [_spec("echo"), _spec("add", "Add numbers")]

        transport.call(prompt="hi", tools=specs, model="test-model")

        sent_tools = mock_client.chat.call_args.kwargs["tools"]
        assert len(sent_tools) == 2
        names = {t["function"]["name"] for t in sent_tools}
        assert names == {"echo", "add"}

    def test_temperature_forwarded_to_provider(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = _raw_text("ok")
        transport = LLMTransport(mock_client)

        transport.call(prompt="hi", tools=[], model="m", temperature=0.9)

        assert mock_client.chat.call_args.kwargs["temperature"] == 0.9
