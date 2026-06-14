"""
Phase 5.0 — S5 Conversational Response Contract
================================================

AgentMessage, AgentResponse, and ActionIntent types for the S5
conversational layer.

S5 produces only declarative *action intents*, never executable
instructions.  Planning (S5.3) and execution dispatch (S5.4) are
handled by downstream layers.

All types are frozen dataclasses — deterministic, JSON‑serializable,
and contain no runtime logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


S5_CONTRACT_VERSION = "1.0"
"""Current contract version for S5 boundary types (Phase 5.0)."""

# ---------------------------------------------------------------------------
# Action intent type constants
# ---------------------------------------------------------------------------

ACTION_CALL_TOOL_INTENT = "call_tool_intent"
"""Declarative intent to call a tool (resolved by S5.3, dispatched by S5.4)."""

ACTION_REQUEST_S4_JOB_INTENT = "request_s4_job_intent"
"""Declarative intent to request an S4 job (resolved by S5.3, dispatched by S5.4)."""

ACTION_AGENT_STEP_INTENT = "agent_step_intent"
"""Declarative intent for a multi-step agent action (resolved by S5.3)."""

VALID_ACTION_INTENT_TYPES = frozenset({
    ACTION_CALL_TOOL_INTENT,
    ACTION_REQUEST_S4_JOB_INTENT,
    ACTION_AGENT_STEP_INTENT,
})

# ---------------------------------------------------------------------------
# ActionIntent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionIntent:
    """
    A declarative action intent emitted by S5.

    This is *not* an executable instruction.  It is a request for the
    downstream planning layer (S5.3) and execution layer (S5.4) to
    resolve and dispatch.

    Fields
    ------
    type:
        One of VALID_ACTION_INTENT_TYPES.
    payload:
        Arbitrary JSON‑compatible data describing the intent.
    description:
        Human‑readable description of the intent (for logging/debugging).
    """

    type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        if self.type not in VALID_ACTION_INTENT_TYPES:
            raise ValueError(
                f"action_intent.type must be one of "
                f"{sorted(VALID_ACTION_INTENT_TYPES)}, got {self.type!r}"
            )
        if not isinstance(self.payload, dict):
            raise ValueError("action_intent.payload must be a dict")
        # Ensure payload is JSON‑compatible at construction time
        _require_json_compatible(self.payload, "action_intent.payload")


# ---------------------------------------------------------------------------
# AgentMessage  (inbound)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentMessage:
    """
    Inbound message from a user, received via an S4 channel.

    Fields
    ------
    message:
        Raw natural‑language input from the user.
    context:
        Channel metadata, conversation history, and routing hints.
    capabilities:
        What this agent can do (not what it will do).
    contract_version:
        S5 contract version for forward compatibility.
    """

    message: str
    context: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    contract_version: str = S5_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.message:
            raise ValueError("message must be non-empty")
        if not isinstance(self.context, dict):
            raise ValueError("context must be a dict")
        if not isinstance(self.capabilities, list):
            raise ValueError("capabilities must be a list")
        if not self.contract_version:
            raise ValueError("contract_version must be non-empty")
        _require_json_compatible(self.context, "context")
        _require_json_compatible(self.capabilities, "capabilities")


# ---------------------------------------------------------------------------
# AgentResponse  (outbound)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentResponse:
    """
    Outbound response from S5 to the user.

    S5 produces natural‑language replies and declarative action intents.
    It never produces executable instructions, S1 drift/repair schemas,
    S4 job envelopes, or planner structures.

    Fields
    ------
    reply:
        Natural‑language output (haiku, answer, explanation).  None when
        the response consists only of action intents.
    actions:
        Declarative action intents for downstream layers to resolve.
        May be empty when the response is purely conversational.
    metadata:
        Correlation IDs, provenance, confidence score.
    contract_version:
        S5 contract version for forward compatibility.
    """

    reply: Optional[str] = None
    actions: List[ActionIntent] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    contract_version: str = S5_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.reply is not None and not isinstance(self.reply, str):
            raise ValueError("reply must be a string or None")
        if not isinstance(self.actions, list):
            raise ValueError("actions must be a list")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dict")
        if not self.contract_version:
            raise ValueError("contract_version must be non-empty")

        # At least one of reply or actions must be present
        if self.reply is None and not self.actions:
            raise ValueError(
                "AgentResponse must have at least one of reply or actions"
            )

        _require_json_compatible(self.metadata, "metadata")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_json_compatible(
    obj: Any, path: str, depth: int = 0
) -> None:
    """Assert that *obj* contains only JSON‑compatible types.

    Raises ``ValueError`` (not ``TypeError``) so callers can use a
    uniform exception type.  Acceptable leaf types are ``None``, ``bool``,
    ``int``, ``float``, ``str``, and ``list``/``dict`` of the same.
    """
    if depth > 50:
        raise ValueError(
            f"{path} exceeds maximum nesting depth of 50"
        )
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return
    if isinstance(obj, (list, tuple)):
        _require_json_compatible_iterable(
            obj, path, depth
        )
        return
    if isinstance(obj, dict):
        _require_json_compatible_dict(obj, path, depth)
        return

    raise ValueError(
        f"{path} contains non‑JSON‑compatible value {type(obj).__name__}"
    )


def _require_json_compatible_iterable(
    items: Any, path: str, depth: int
) -> None:
    for i, item in enumerate(items):
        _require_json_compatible(item, f"{path}[{i}]", depth + 1)


def _require_json_compatible_dict(
    d: Dict[str, Any], path: str, depth: int
) -> None:
    for key, value in d.items():
        if not isinstance(key, str):
            raise ValueError(
                f"{path} contains non‑string key {type(key).__name__}"
            )
        _require_json_compatible(value, f"{path}.{key}", depth + 1)
