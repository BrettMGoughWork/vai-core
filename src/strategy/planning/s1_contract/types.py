"""
Phase 2.14.1 — S1 Contract Types
=================================

Typed boundary types for S2↔S1 communication.

These types are **owned by S2** — they define the boundary contract
that S2 uses to talk to S1.  S1 does not import them.

All types are pure dataclasses with JSON-safe fields.
No I/O, no inference, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


# ──────────────────────────────────────────────────────────────────────────────
# S2 → S1: structured prompt request
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class PromptRequest:
    """Structured request from S2 (reasoner) to S1 (LLM/tooling).

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
# S1 → S2: structured prompt response
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class PromptResponse:
    """Structured response from S1 (LLM/tooling) to S2 (reasoner)."""

    output: Dict[str, Any]          # structured LLM output
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)  # optional tool call requests
    errors: List[Dict[str, Any]] = field(default_factory=list)      # schema/format errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output": self.output,
            "tool_calls": self.tool_calls,
            "errors": self.errors,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Tool call types (S1 → S2, S2 → S1)
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class ToolCallRequest:
    """A request for S1 to execute a tool call."""

    name: str
    arguments: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
        }


@dataclass
class ToolCallResult:
    """Result of a tool call execution in S1, returned to S2."""

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
    """Structured error from S1 to S2."""

    type: str        # error category e.g. "timeout", "schema_error", "tool_error"
    message: str     # human-readable summary
    details: Dict[str, Any] = field(default_factory=dict)  # structured context

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            "details": self.details,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Domain-name aliases
# ──────────────────────────────────────────────────────────────────────────────

LLMBackendError = S1Error
"""Domain alias — S1Error is the canonical Runtime LLM-backend error type."""
