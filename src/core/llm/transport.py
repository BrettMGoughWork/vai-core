from __future__ import annotations
from typing import List, Dict, Any

from .types import CoreLLMResponse
from src.core.skills.toolspec import ToolSpec


class LLMTransport:
    """
    Single entrypoint for all LLM calls.
    Vendor-specific logic lives here only.
    """

    def __init__(self, client):
        self.client = client  # e.g. OpenAI, Anthropic, DeepSeek

    def call(
        self,
        prompt: str,
        tools: List[ToolSpec],
        model: str,
        temperature: float = 0.2,
    ) -> CoreLLMResponse:
        """
        Call the LLM with tools and parse the response.
        """
        # Convert ToolSpecs → provider schema
        tool_defs = [self._convert_tool_spec(t) for t in tools]

        # Call the provider
        raw = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            tools=tool_defs,
            temperature=temperature,
        )

        return self._parse_response(raw)

    # ---------------------------------------------------------
    # Convert ToolSpec → provider tool schema
    # ---------------------------------------------------------
    def _convert_tool_spec(self, spec: ToolSpec) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.schema,
            },
        }

    # ---------------------------------------------------------
    # Parse provider response → CoreLLMResponse
    # ---------------------------------------------------------
    def _parse_response(self, raw) -> CoreLLMResponse:
        msg = raw.choices[0].message

        # Tool call
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            return CoreLLMResponse(
                tool_name=tc.function.name,
                tool_args=tc.function.arguments,
            )

        # Normal text
        return CoreLLMResponse(text=msg.content)