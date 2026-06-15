"""
Gateway → S5 Adapter Protocol
==============================

Defines the boundary between Stratum-4 (Gateway) and Stratum-5 (Agent
Supervisor).  The Gateway normalises channel input, wraps it as an
``AgentRequest``, and calls ``ingest()``.  S5 processes the request
and returns a response dict.

This replaces the legacy ``GatewayPlatformAdapter`` (Gateway → S4 Jobs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol


@dataclass(frozen=True)
class AgentRequest:
    """Normalised request from a channel, destined for S5.

    Fields
    ------
    channel:
        The originating channel (e.g. ``"cli"``, ``"web"``).
    message_text:
        The natural-language message text from the user.
    user_id:
        Optional user or sender identifier.
    metadata:
        Additional channel metadata (correlation ids, headers, etc.).
    """

    channel: str
    message_text: str
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.channel:
            raise ValueError("channel must be non-empty")
        if not self.message_text:
            raise ValueError("message_text must be non-empty")


class GatewayAgentAdapter(Protocol):
    """Protocol that the Gateway calls to hand off to S5.

    Implementations receive a normalised ``AgentRequest`` and return a
    response dict.  The response shape depends on the outcome:

    - Success:  ``{"reply": str, "metadata": dict}``
    - Pending:  ``{"state": "waiting", "agent_id": str}``
    - Error:    ``{"error": str}``
    """

    def ingest(self, request: AgentRequest) -> Dict[str, Any]:
        """Send a normalised request to S5 for processing.

        Args:
            request: The normalised channel request.

        Returns:
            A dict describing the outcome (see class docstring).
        """
        ...
