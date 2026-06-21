from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMCallable(Protocol):
    """Structural protocol for any object that can make an LLM call."""

    def call(
        self,
        prompt: str,
        tools: List[Any],
        model: str,
        temperature: float = 0.2,
    ) -> "CoreLLMResponse": ...


@dataclass
class CoreLLMResponse:
    """
    Normalised LLM output:
    - text: normal assistant message
    - tool_name: if the LLM wants to call a tool
    - tool_args: parsed arguments for the tool
    - tool_calls: raw tool_calls from the LLM when multiple are returned
    """
    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


@dataclass
class RuntimeConfig:
    """Configuration for an LLM runtime call.

    Replaces the S2-owned LLMConfig so that S1 (runtime)
    has no dependency on S2 types.
    """
    provider: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 4096