"""
Domain Stratum — S1 Contract Types
===================================

Typed boundary types for cross-stratum communication.

These types are **owned by the domain** — they define the boundary contract
that all strata use to communicate.  All types are pure dataclasses with
JSON-safe fields.  No I/O, no inference, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


# ──────────────────────────────────────────────────────────────────────────────
# Structured prompt request
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class PromptRequest:
    """Structured request from a consumer to an LLM/tooling backend.

    All fields are JSON-safe.  No raw strings cross the boundary without
    being wrapped in a typed container.
    """

    prompt: Dict[str, Any]          # structured prompt payload
    memory: Dict[str, Any]          # memory snapshot
    plan_context: Dict[str, Any]    # summaries of subgoal/segment state
    tool_context: List[Dict[str, Any]] = field(default_factory=list)  # available tools + schemas

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "memory": self.memory,
            "plan_context": self.plan_context,
            "tool_context": self.tool_context,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Structured prompt response
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class PromptResponse:
    """Structured response from an LLM/tooling backend to a consumer."""

    output: Dict[str, Any]          # structured LLM output
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)  # optional tool call requests
    errors: List[Dict[str, Any]] = field(default_factory=list)      # schema/format errors
    input_tokens: int = 0           # token count of input (messages + tools)
    context_pressure: float = 0.0   # input_tokens / safe_context_limit (0.0-1.0+)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output": self.output,
            "tool_calls": self.tool_calls,
            "errors": self.errors,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Tool call types
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class ToolCallRequest:
    """A request to execute a tool call."""

    name: str
    arguments: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
        }


@dataclass
class ToolCallResult:
    """Result of a tool call execution."""

    name: str
    result: Dict[str, Any]
    success: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "result": self.result,
            "success": self.success,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Error type
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class S1Error:
    """Structured error from infrastructure to consumer."""

    type: str        # error category e.g. "timeout", "schema_error", "tool_error"
    message: str     # human-readable summary
    details: Dict[str, Any] = field(default_factory=dict)  # structured context

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            "details": self.details,
        }
