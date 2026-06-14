"""
Phase R.1 — Runtime Contract
=============================

Defines the contract between the Agent layer (S5) and the LLM Runtime.

The Runtime is the **only** way an LLM can be called.  It abstracts over
different backends (DeepSeek, GPT, Claude, simulation, etc.) behind a
single interface.

Components
----------
- ``RuntimeRequest`` — input envelope for an LLM generation
- ``RuntimeResponse`` — output envelope from an LLM generation
- ``Runtime`` — abstract base class for all runtime backends
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# RuntimeRequest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeRequest:
    """Input envelope for an LLM generation.

    Attributes:
        message: The user or system message to send to the LLM.
        agent_id: Identifies which agent is making the request.
        conversation_history: Optional prior turns for context.
        system_prompt: Optional system-level instruction override.
        metadata: Arbitrary key/value metadata (correlation_id,
                  trace_id, temperature, max_tokens, etc.).
    """

    message: str
    agent_id: str
    conversation_history: Optional[List[Dict[str, Any]]] = None
    system_prompt: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# RuntimeResponse
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeResponse:
    """Output envelope from an LLM generation.

    Attributes:
        reply: The generated text response.
        confidence: Model confidence score (0.0 – 1.0).
        metadata: Arbitrary key/value metadata (model_name,
                  token_count, latency_ms, finish_reason, etc.).
    """

    reply: str
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Runtime (ABC)
# ---------------------------------------------------------------------------


class Runtime(ABC):
    """Abstract interface for LLM runtime backends.

    Every backend (real LLM, simulation, mock, etc.) implements this
    single method.
    """

    @abstractmethod
    def generate(self, request: RuntimeRequest) -> RuntimeResponse:
        """Send a request to the LLM and return the response.

        Args:
            request: The fully-specified request envelope.

        Returns:
            The LLM's response.

        Raises:
            RuntimeError: If the backend is unavailable or returns
                          an error.
        """
        ...
