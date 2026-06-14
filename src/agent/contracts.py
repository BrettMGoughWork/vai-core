"""
Phase 5.0 — S5 Conversational Response Contract
================================================

AgentMessage and AgentResponse types for the S5 conversational layer.

S5 produces only natural-language replies.  Routing decisions are
handled by the Agent Router (Phase 5.2), not by action intents.

All types are frozen dataclasses — deterministic, JSON‑serializable,
and contain no runtime logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


S5_CONTRACT_VERSION = "1.0"
"""Current contract version for S5 boundary types (Phase 5.0)."""

# ---------------------------------------------------------------------------
# AgentMessage  (inbound)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentMessage:
    """
    Inbound message from a user, received via a channel (S4).

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
    capabilities: list[str] = field(default_factory=list)
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

    S5 produces natural‑language replies only.  It never produces
    executable instructions, action intents, S1 drift/repair schemas,
    S4 job envelopes, or planner structures.

    Fields
    ------
    reply:
        Natural‑language output (answer, explanation, response).  None
        when the agent has nothing to say.
    metadata:
        Correlation IDs, provenance, confidence score.
    contract_version:
        S5 contract version for forward compatibility.
    """

    reply: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    contract_version: str = S5_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.reply is not None and not isinstance(self.reply, str):
            raise ValueError("reply must be a string or None")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dict")
        if not self.contract_version:
            raise ValueError("contract_version must be non-empty")
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
