from __future__ import annotations

from dataclasses import dataclass
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
    """
    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None