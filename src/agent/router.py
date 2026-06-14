"""
Phase 5.2 — Agent Router (inspect → match → dispatch)
=======================================================

Pure inspection and routing — no LLM calls, no intents, no side effects.
The router is a deterministic pattern matcher that decides where an
inbound message should be dispatched based on content and agent metadata.

Destinations
------------
- ``runtime`` — conversational / chat (→ Runtime stratum)
- ``s6``      — multi-step workflow (→ Workflow Engine)
- ``s4b``     — direct platform job execution (→ Platform stratum)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.agent.registry import AgentMetadata, CAP_JOB_SUBMISSION

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROUTER_VERSION = "1.0"
"""Current version of the router schema."""

# Route destinations
DEST_RUNTIME = "runtime"  # → conversational LLM (chat / assistant)
DEST_S6 = "s6"            # → workflow engine (multi-step / orchestration)
DEST_S4B = "s4b"          # → platform job (direct tool execution)

# Keywords that hint at workflow intent
_WORKFLOW_KEYWORDS = frozenset({
    "run workflow", "start workflow", "workflow",
    "trigger workflow", "execute workflow",
})

# Keywords that hint at direct execution intent
_EXECUTION_KEYWORDS = frozenset({
    "execute ", "run ", "do ",
})


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    """Result of routing a message through the agent router.

    Fields
    ------
    destination:
        Where this message should be dispatched — one of ``DEST_*``.
    payload:
        Data to pass to the destination handler.  Always includes the
        original ``message`` and may include destination-specific keys.
    agent_id:
        The originating agent's identifier.
    confidence:
        Confidence in this routing decision (0.0 — 1.0).
    """

    destination: str
    payload: Dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""
    confidence: float = 1.0

    def __post_init__(self) -> None:
        valid = {DEST_RUNTIME, DEST_S6, DEST_S4B}
        if self.destination not in valid:
            raise ValueError(
                f"destination must be one of {sorted(valid)}, "
                f"got {self.destination!r}"
            )
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a dict")
        if not isinstance(self.confidence, (int, float)):
            raise ValueError("confidence must be a number")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0.0, 1.0]")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def route_message(
    message: str,
    agent: AgentMetadata,
    context: Optional[Dict[str, Any]] = None,
) -> Route:
    """Inspect an inbound message and decide where it should be routed.

    Pure pattern matching — no LLM calls, no side effects.  Uses message
    content and agent capabilities to determine the correct destination.

    Parameters
    ----------
    message:
        The raw user message to inspect.
    agent:
        The agent's metadata (used to check declared capabilities).
    context:
        Optional activation context for richer routing decisions.

    Returns
    -------
    Route
        Routing decision with destination and payload.
    """
    ctx = context or {}
    _ = ctx  # reserved for future context-based routing
    msg_lower = message.strip().lower()

    # ── 1. Workflow keywords → S6 ────────────────────────────────────
    if any(kw in msg_lower for kw in _WORKFLOW_KEYWORDS):
        return Route(
            destination=DEST_S6,
            payload={
                "message": message,
                "trigger": "workflow_request",
            },
            agent_id=agent.identity.agent_id,
            confidence=0.8,
        )

    # ── 2. Execution keywords + capability → S4b ──────────────────────
    if CAP_JOB_SUBMISSION in agent.capabilities:
        if any(kw in msg_lower for kw in _EXECUTION_KEYWORDS):
            return Route(
                destination=DEST_S4B,
                payload={
                    "message": message,
                    "action": "direct_execution",
                },
                agent_id=agent.identity.agent_id,
                confidence=0.7,
            )

    # ── 3. Default → Runtime (conversational) ────────────────────────
    return Route(
        destination=DEST_RUNTIME,
        payload={"message": message},
        agent_id=agent.identity.agent_id,
        confidence=1.0,
    )
