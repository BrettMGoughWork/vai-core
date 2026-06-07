from __future__ import annotations
import json
from typing import List, Dict, Any

from .types import CoreLLMResponse
from src.core.types.toolspec import ToolSpec
from src.core.llm.providers._base import ChatProvider


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
        raw = self.client.chat(
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
        msg = raw["choices"][0]["message"]

        # Tool call
        if msg.get("tool_calls"):
            tc = msg["tool_calls"][0]
            args = tc["function"].get("arguments")
            if isinstance(args, str):
                args = json.loads(args)
            return CoreLLMResponse(
                tool_name=tc["function"]["name"],
                tool_args=args,
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