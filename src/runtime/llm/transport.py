from __future__ import annotations
import json
from typing import List, Dict, Any

from .types import CoreLLMResponse
from .providers._base import ChatProvider


class LLMTransport:
    """
    Single entrypoint for all LLM calls.
    Vendor-specific logic lives here only.
    """

    def __init__(self, client, model: str, temperature: float, max_tokens: int):
        self.client = client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def call(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.2,
    ) -> CoreLLMResponse:
        """
        Call the LLM with tools and parse the response.
        """
        # Call the provider
        raw = self.client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            temperature=temperature,
        )

        return self._parse_response(raw)

    # ---------------------------------------------------------
    # Parse provider response → CoreLLMResponse
    # ---------------------------------------------------------
    def _parse_response(self, raw) -> CoreLLMResponse:
        msg = raw["choices"][0]["message"]

        # Tool call
        if msg.get("tool_calls"):
            raw_tool_calls = msg["tool_calls"]
            tc = raw_tool_calls[0]
            args = tc["function"].get("arguments")
            if isinstance(args, str):
                args = json.loads(args)
            return CoreLLMResponse(
                tool_name=tc["function"]["name"],
                tool_args=args,
                tool_calls=raw_tool_calls,
            )

        # Normal text
        return CoreLLMResponse(text=msg.get("content"))

    def complete(self, prompt: str) -> str:
        resp = self.client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return resp["choices"][0]["message"]["content"]

    # ---------------------------------------------------------
    # Tool-aware completion (native function calling)
    # ---------------------------------------------------------

    def complete_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> CoreLLMResponse:
        """Call the LLM with structured messages and tool definitions.

        Uses the instance's configured model, temperature and max_tokens.
        Returns a CoreLLMResponse with either text (no tool chosen) or
        tool_name/tool_args/tool_calls (tool chosen by the LLM).
        """
        raw = self.client.chat(
            model=self.model,
            messages=messages,
            tools=tools,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        return self._parse_response(raw)