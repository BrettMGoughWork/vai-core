"""
S5 → S1: LLM Execution Protocol
================================

Defines the contract between the orchestrator (S5) and the runtime
LLM backend (S1).  S5 calls ``complete()`` or ``complete_with_tools()``;
S1 executes the LLM call and returns a normalised ``CoreLLMResponse``.

This is the **only** way S5 interacts with the LLM — no direct imports
of S1 implementation details.

Contract
--------
- ``complete()``  — plain LLM call (no tool definitions)
- ``complete_with_tools()`` — LLM call with tool definitions (dicts in
  provider schema format)
- Both methods are synchronous and return ``CoreLLMResponse``
- Tool definitions are opaque dicts — the caller converts them to
  provider schema format before passing
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from src.runtime.llm.types import CoreLLMResponse


@runtime_checkable
class S1Executor(Protocol):
    """S5 → S1: Execute an LLM call.

    Implementations wrap the LLM transport layer and handle provider
    selection, configuration, and response parsing.
    """

    def complete(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CoreLLMResponse:
        """Plain LLM call — no tool definitions.

        Args:
            prompt: The user/agent message to send to the LLM.
            context: Optional structured context (memory, plan state, etc.).

        Returns:
            A normalised ``CoreLLMResponse`` containing text and/or tool call.
        """
        ...

    def complete_with_tools(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> CoreLLMResponse:
        """LLM call with tool definitions.

        Tool definitions are opaque dicts in provider schema format
        (e.g. OpenAI tool format).  The caller is responsible for
        converting domain tool specs before calling.

        Args:
            prompt: The user/agent message to send to the LLM.
            tools: Tool definitions in provider schema format.
            context: Optional structured context.

        Returns:
            A normalised ``CoreLLMResponse`` containing text and/or tool call.
        """
        ...
