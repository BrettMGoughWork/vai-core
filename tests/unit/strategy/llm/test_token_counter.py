"""Tests for the token counting utility."""

from __future__ import annotations

import pytest

from src.runtime.llm.token_counter import (
    TokenCounter,
    count_tokens_in_text,
    count_tokens_in_messages,
    count_tokens_in_tools,
    get_context_limit,
)


class TestTokenCounter:
    """Unit tests for TokenCounter class."""

    def test_count_text_empty(self):
        counter = TokenCounter()
        assert counter.count_text("") == 0

    def test_count_text_short(self):
        counter = TokenCounter()
        # "hello world" should produce some positive token count
        assert counter.count_text("hello world") > 0

    def test_count_text_longer(self):
        counter = TokenCounter()
        short = counter.count_text("hello world")
        long_ = counter.count_text("hello world " * 100)
        assert long_ > short

    def test_count_message_simple(self):
        counter = TokenCounter()
        msg = {"role": "user", "content": "hello"}
        assert counter.count_message(msg) > 0

    def test_count_message_with_tool_calls(self):
        counter = TokenCounter()
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "edit_file",
                        "arguments": '{"path": "test.py", "content": "print(1)"}',
                    }
                }
            ],
        }
        assert counter.count_message(msg) > 0

    def test_count_message_with_tool_call_id(self):
        counter = TokenCounter()
        msg = {"role": "tool", "content": "result", "tool_call_id": "call_123"}
        assert counter.count_message(msg) > 0

    def test_count_messages_list(self):
        counter = TokenCounter()
        msgs = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        assert counter.count_messages(msgs) > 0
        # Sum of individual counts should match bulk count
        individual = sum(counter.count_message(m) for m in msgs)
        assert counter.count_messages(msgs) == individual

    def test_count_tool_definitions_empty(self):
        counter = TokenCounter()
        assert counter.count_tool_definitions([]) == 0

    def test_count_tool_definitions_with_tools(self):
        counter = TokenCounter()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read contents of a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                        },
                    },
                },
            }
        ]
        assert counter.count_tool_definitions(tools) > 0

    def test_get_context_limit_known_model(self):
        limit = get_context_limit("gpt-4o", output_budget=4096)
        assert limit == 128000 - 4096

    def test_get_context_limit_unknown_model(self):
        limit = get_context_limit("unknown-model")
        assert limit is None

    def test_get_context_limit_zero_budget(self):
        limit = get_context_limit("deepseek-chat", output_budget=0)
        assert limit == 65536


class TestModuleLevelConvenience:
    """Tests for the module-level convenience functions."""

    def test_count_tokens_in_text(self):
        n = count_tokens_in_text("hello world")
        assert isinstance(n, int)
        assert n > 0

    def test_count_tokens_in_messages(self):
        msgs = [{"role": "user", "content": "test"}]
        n = count_tokens_in_messages(msgs)
        assert isinstance(n, int)
        assert n > 0

    def test_count_tokens_in_tools(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "description": "A test tool",
                    "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
                },
            }
        ]
        n = count_tokens_in_tools(tools)
        assert isinstance(n, int)
        assert n > 0
