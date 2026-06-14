"""
Phase 5.2 — Agent Activation Contract
========================================

Defines how an agent is activated, what context it receives, how its
capabilities are resolved, and who is allowed to activate S5.

S5 is the primary cognitive entrypoint.  It can be activated directly
by user-facing channels (CLI, HTTP, TUI, Web) or by S6 (future
orchestration layer).  S4 — an execution layer — never activates S5.

Activation is purely *preparation*: it builds the envelope, resolves
capabilities, and injects context, but never runs the agent, never
plans, never dispatches actions, and never submits S4 jobs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agent.contracts import AgentMessage
from src.agent.registry import (
    AgentMetadata,
    AgentNotFoundError,
    AgentRegistry,
)

# ---------------------------------------------------------------------------
# Channel type constants
# ---------------------------------------------------------------------------

CHANNEL_CLI = "cli"
CHANNEL_HTTP = "http"
CHANNEL_TUI = "tui"
CHANNEL_WEB = "web"
CHANNEL_SYSTEM = "system"

VALID_CHANNELS = frozenset({
    CHANNEL_CLI,
    CHANNEL_HTTP,
    CHANNEL_TUI,
    CHANNEL_WEB,
    CHANNEL_SYSTEM,
})

# Channels that are allowed to activate S5.
ACTIVATION_AUTHORIZED_CHANNELS = frozenset({
    CHANNEL_CLI,
    CHANNEL_HTTP,
    CHANNEL_TUI,
    CHANNEL_WEB,
    CHANNEL_SYSTEM,  # S6 activates via the "system" channel
})

# ---------------------------------------------------------------------------
# Channel-to-capability constraints
# ---------------------------------------------------------------------------
# Some capabilities may be restricted on certain channels.  The dict
# below lists capabilities that are *blocked* per channel.
#   key   = channel name
#   value = frozenset of blocked capability labels

CHANNEL_CAPABILITY_BLOCKLIST: Dict[str, frozenset] = {
    # The CLI is text-only — no tool-use or job-submission over stdin.
    CHANNEL_CLI: frozenset(),
    # Web channels may restrict certain analysis paths for safety.
    CHANNEL_WEB: frozenset(),
    # All other channels currently have no blocklisted capabilities.
}

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ActivationError(Exception):
    """Base error for activation operations."""


class UnauthorizedChannelError(ActivationError):
    """Raised when an unauthorized source attempts to activate S5."""


# ---------------------------------------------------------------------------
# ActivationEnvelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivationEnvelope:
    """Wraps an AgentMessage with activation metadata.

    This is the outermost container for an activation request.  It adds
    correlation/trace IDs, channel provenance, and a timestamp so that
    every activation is fully auditable.

    Fields
    ------
    agent_id:
        The agent being activated.
    message:
        The inbound user message (or system event).
    activation_context:
        Metadata about the activation itself — timestamp, channel,
        correlation_id, trace_id.
    """

    agent_id: str
    message: AgentMessage
    activation_context: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("agent_id must be non-empty")
        if not isinstance(self.message, AgentMessage):
            raise ValueError("message must be an AgentMessage instance")
        if not isinstance(self.activation_context, dict):
            raise ValueError("activation_context must be a dict")

        channel = self.activation_context.get("channel", "")
        if channel and channel not in VALID_CHANNELS:
            raise ValueError(
                f"channel must be one of {sorted(VALID_CHANNELS)}, "
                f"got {channel!r}"
            )


# ---------------------------------------------------------------------------
# ActivationContext (injected context)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivationContext:
    """Context injected into the agent at activation time.

    This is the read‑only, deterministic context that the agent receives
    when it is activated.  It includes everything the agent needs to
    understand the conversation and its own capabilities, but nothing
    about S4 state, worker state, execution envelopes, or planning
    structures.

    Fields
    ------
    agent_metadata:
        The agent's own metadata (identity, capabilities, constraints).
    resolved_capabilities:
        Capabilities that are available for *this* activation, after
        channel‑based filtering.
    conversation_history:
        Prior messages in the conversation (may be empty).
    routing_hints:
        Optional hints about where responses should be routed.
    channel_metadata:
        Metadata about the channel that initiated this activation.
    system_constraints:
        System‑level constraints for this activation (e.g. token limits,
        timeouts inherited from the agent's constraints).
    """

    agent_metadata: AgentMetadata
    resolved_capabilities: List[str] = field(default_factory=list)
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    routing_hints: Dict[str, Any] = field(default_factory=dict)
    channel_metadata: Dict[str, Any] = field(default_factory=dict)
    system_constraints: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.agent_metadata, AgentMetadata):
            raise ValueError(
                "agent_metadata must be an AgentMetadata instance"
            )
        if not isinstance(self.resolved_capabilities, list):
            raise ValueError("resolved_capabilities must be a list")
        if not isinstance(self.conversation_history, list):
            raise ValueError("conversation_history must be a list")
        if not isinstance(self.routing_hints, dict):
            raise ValueError("routing_hints must be a dict")
        if not isinstance(self.channel_metadata, dict):
            raise ValueError("channel_metadata must be a dict")
        if not isinstance(self.system_constraints, dict):
            raise ValueError("system_constraints must be a dict")


# ---------------------------------------------------------------------------
# ActivatedAgentContext
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivatedAgentContext:
    """Complete context produced by a successful activation.

    This is the output of ``activate_agent()``.  It bundles the
    activation envelope with the resolved context so that downstream
    layers (S5.3 planner) have everything they need to run the agent.

    Fields
    ------
    envelope:
        The activation envelope (agent_id, message, activation_context).
    context:
        The resolved, injected context (metadata, capabilities, history).
    """

    envelope: ActivationEnvelope
    context: ActivationContext

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, ActivationEnvelope):
            raise ValueError("envelope must be an ActivationEnvelope instance")
        if not isinstance(self.context, ActivationContext):
            raise ValueError("context must be an ActivationContext instance")


# ---------------------------------------------------------------------------
# Capability resolution
# ---------------------------------------------------------------------------


def resolve_capabilities(
    agent_metadata: AgentMetadata,
    channel: str,
) -> List[str]:
    """Resolve the capabilities available for *agent* on *channel*.

    Starts from the agent's declared capabilities and filters out any
    capabilities that are blocklisted for the given channel.

    Parameters
    ----------
    agent_metadata:
        The agent's registered metadata.
    channel:
        The channel initiating the activation.

    Returns
    -------
    list[str]
        Capabilities available for this activation, in declaration order.
    """
    blocked = CHANNEL_CAPABILITY_BLOCKLIST.get(channel, frozenset())
    return [cap for cap in agent_metadata.capabilities if cap not in blocked]


# ---------------------------------------------------------------------------
# Agent Activation API
# ---------------------------------------------------------------------------


def activate_agent(
    agent_id: str,
    message: AgentMessage,
    registry: AgentRegistry,
    *,
    channel: str = CHANNEL_CLI,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    routing_hints: Optional[Dict[str, Any]] = None,
    channel_metadata: Optional[Dict[str, Any]] = None,
) -> ActivatedAgentContext:
    """Activate an agent — prepare it to think.

    This is the single entry-point for activating any agent.  It is:

    - **deterministic** (given the same inputs, returns the same context)
    - **read‑only** (never mutates the registry or agent metadata)
    - **side‑effect‑free** (no I/O, no dispatch, no planning)
    - **non‑executing** (does not run the agent)

    Parameters
    ----------
    agent_id:
        The agent to activate.
    message:
        The inbound message from the user or system.
    registry:
        The agent registry for lookups.
    channel:
        The channel initiating the activation.  Must be one of
        ``VALID_CHANNELS`` and in ``ACTIVATION_AUTHORIZED_CHANNELS``.
    correlation_id:
        Optional correlation ID.  Auto-generated if not provided.
    trace_id:
        Optional trace ID.  Auto-generated if not provided.
    conversation_history:
        Optional prior conversation turns.
    routing_hints:
        Optional routing hints for the response.
    channel_metadata:
        Optional channel-specific metadata.

    Returns
    -------
    ActivatedAgentContext
        The complete, prepared activation context.

    Raises
    ------
    UnauthorizedChannelError
        If *channel* is not in ``ACTIVATION_AUTHORIZED_CHANNELS``.
    ActivationError
        If the agent is not found or inputs are invalid.
    """
    # ── 1. Validate channel authority ──────────────────────────────────
    if channel not in ACTIVATION_AUTHORIZED_CHANNELS:
        raise UnauthorizedChannelError(
            f"channel {channel!r} is not authorized to activate S5; "
            f"authorized channels: {sorted(ACTIVATION_AUTHORIZED_CHANNELS)}"
        )

    # ── 2. Look up agent ──────────────────────────────────────────────
    try:
        metadata = registry.get_agent(agent_id)
    except AgentNotFoundError:
        raise ActivationError(
            f"cannot activate unknown agent {agent_id!r}"
        )

    # ── 3. Resolve capabilities ───────────────────────────────────────
    resolved = resolve_capabilities(metadata, channel)

    # ── 4. Build activation context (metadata) ────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    cid = correlation_id or str(uuid.uuid4())
    tid = trace_id or str(uuid.uuid4())

    activation_context: Dict[str, Any] = {
        "timestamp": now,
        "channel": channel,
        "correlation_id": cid,
        "trace_id": tid,
    }

    # ── 5. Build injected context ─────────────────────────────────────
    constraints = metadata.constraints
    system_constraints: Dict[str, Any] = {
        "max_tokens": constraints.max_tokens,
        "timeout_ms": constraints.timeout_ms,
        "sandbox": constraints.sandbox,
    }

    injected = ActivationContext(
        agent_metadata=metadata,
        resolved_capabilities=resolved,
        conversation_history=conversation_history or [],
        routing_hints=routing_hints or {},
        channel_metadata=channel_metadata or {},
        system_constraints=system_constraints,
    )

    # ── 6. Build envelope ─────────────────────────────────────────────
    envelope = ActivationEnvelope(
        agent_id=agent_id,
        message=message,
        activation_context=activation_context,
    )

    # ── 7. Return prepared context ────────────────────────────────────
    return ActivatedAgentContext(envelope=envelope, context=injected)
