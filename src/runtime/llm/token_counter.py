"""
Token counting for context-window management.

Uses tiktoken with cl100k_base encoding (GPT-4 / GPT-4o / most modern models).
Supports pluggable encodings for non-OpenAI models.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import tiktoken

# Default encoding — covers GPT-4, GPT-4o, GPT-4-turbo, DeepSeek-V2+, etc.
DEFAULT_ENCODING = "cl100k_base"

# Known context-window limits by model (input + output). Output budgets
# are subtracted to arrive at the "safe input" ceiling.
MODEL_CONTEXT_LIMITS: Dict[str, int] = {
    "deepseek-chat": 65536,
    "deepseek-reasoner": 65536,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "claude-3-5-sonnet-20241022": 200000,
    "claude-3-opus-20240229": 200000,
    "gemini-2.0-flash": 1048576,
    "gemini-1.5-pro": 2097152,
    "qwen-max": 32768,
    "mistral-large": 131000,
}


class TokenCounter:
    """Count tokens in messages, tool definitions, and conversation history."""

    def __init__(self, encoding_name: str = DEFAULT_ENCODING):
        self._encoding = tiktoken.get_encoding(encoding_name)

    def count_text(self, text: str) -> int:
        """Count tokens in a plain string."""
        return len(self._encoding.encode(text))

    def count_message(self, msg: Dict[str, Any]) -> int:
        """Count tokens in a single message dict (role + content + tool_calls)."""
        # OpenAI formula: 4 tokens per message + role + content
        tokens = 4  # message framing overhead
        for key in ("role", "content"):
            if key in msg and isinstance(msg[key], str):
                tokens += len(self._encoding.encode(msg[key]))
        # tool_calls contribute name + arguments tokens
        if "tool_calls" in msg and isinstance(msg["tool_calls"], list):
            for tc in msg["tool_calls"]:
                func = tc.get("function", {})
                tokens += len(self._encoding.encode(func.get("name", "")))
                tokens += len(self._encoding.encode(func.get("arguments", "{}")))
                tokens += 4  # tool_call framing overhead
        if "tool_call_id" in msg:
            tokens += len(self._encoding.encode(str(msg["tool_call_id"])))
        return tokens

    def count_messages(self, messages: List[Dict[str, Any]]) -> int:
        """Count tokens across a list of messages."""
        return sum(self.count_message(m) for m in messages)

    def count_tool_definitions(self, tools: List[Dict[str, Any]]) -> int:
        """Count tokens consumed by tool/function definitions."""
        tokens = 0
        for tool in tools:
            func = tool.get("function", {})
            tokens += len(self._encoding.encode(func.get("name", "")))
            tokens += len(self._encoding.encode(func.get("description", "")))
            params = func.get("parameters", {})
            if params:
                tokens += len(self._encoding.encode(json.dumps(params, separators=(",", ":"))))
        return tokens


def get_context_limit(model: str, output_budget: int = 4096) -> Optional[int]:
    """Return safe input token ceiling for a model."""
    limit = MODEL_CONTEXT_LIMITS.get(model)
    if limit is None:
        return None
    return limit - output_budget


# Module-level convenience
_counter = TokenCounter()
count_tokens_in_text = _counter.count_text
count_tokens_in_messages = _counter.count_messages
count_tokens_in_tools = _counter.count_tool_definitions
