"""
Agent Stratum — Integration Interfaces
=======================================

Canonical re-exports of the Agent stratum's contracts.

The Agent stratum owns:
- Activation types (ActivatedAgentContext, ActivationEnvelope, …)
- Contract types (AgentMessage, ActionIntent, …)
- Registry types (AgentMetadata, AgentIdentity, …)
- Cognitive loop result types
"""

from __future__ import annotations

# ── Activation Types ──────────────────────────────────────────────────────

from src.agent.activation import (
    ActivatedAgentContext as ActivatedAgentContext,
    ActivationContext as ActivationContext,
    ActivationEnvelope as ActivationEnvelope,
    ACTIVATION_AUTHORIZED_CHANNELS as ACTIVATION_AUTHORIZED_CHANNELS,
    CHANNEL_CLI as CHANNEL_CLI,
    CHANNEL_HTTP as CHANNEL_HTTP,
    CHANNEL_TUI as CHANNEL_TUI,
    CHANNEL_WEB as CHANNEL_WEB,
    CHANNEL_SYSTEM as CHANNEL_SYSTEM,
)

# ── Contract Types ────────────────────────────────────────────────────────

from src.agent.contracts import (
    AgentMessage as AgentMessage,
)

# ── Registry Types ────────────────────────────────────────────────────────

from src.agent.registry import (
    AgentRegistry as AgentRegistry,
    AgentMetadata as AgentMetadata,
    AgentIdentity as AgentIdentity,
    AgentConstraints as AgentConstraints,
    AgentNotFoundError as AgentNotFoundError,
    CAP_CONVERSATIONAL as CAP_CONVERSATIONAL,
    CAP_TOOL_USE as CAP_TOOL_USE,
    CAP_JOB_SUBMISSION as CAP_JOB_SUBMISSION,
)

# ── Cognitive Loop Types ──────────────────────────────────────────────────

# CognitiveLoopResult lives in cognitive_loop.py — import it from the
# canonical source directly rather than through this shim to avoid
# a circular import (cognitive_loop.py → agent.interfaces → cognitive_loop.py).

# ── Job Interface Types ───────────────────────────────────────────────────

from src.agent.job_interface import (
    JobDispatchResult as JobDispatchResult,
    dispatch_route as dispatch_route,
)
from src.agent.router import (
    DEST_RUNTIME as DEST_RUNTIME,
    DEST_S4B as DEST_S4B,
    DEST_WORKFLOW as DEST_WORKFLOW,
    Route as Route,
    route_message as route_message,
)

# ── Supervisor Types (S5.5) ─────────────────────────────────────────────

from src.agent.interfaces.agent_state import (
    AgentState as AgentState,
    LifecycleState as LifecycleState,
    LifecycleEvent as LifecycleEvent,
)

# ── Agent State Store (S5.6) ────────────────────────────────────────────

from src.agent.interfaces.agent_state_store import (
    AgentStateStore as AgentStateStore,
    StoreError as StoreError,
)

__all__ = [
    # Activation
    "ActivatedAgentContext",
    "ActivationContext",
    "ActivationEnvelope",
    "ACTIVATION_AUTHORIZED_CHANNELS",
    "CHANNEL_CLI",
    "CHANNEL_HTTP",
    "CHANNEL_TUI",
    "CHANNEL_WEB",
    "CHANNEL_SYSTEM",
    # Contracts
    "AgentMessage",
    # Registry
    "AgentRegistry",
    "AgentMetadata",
    "AgentIdentity",
    "AgentConstraints",
    "AgentNotFoundError",
    "CAP_CONVERSATIONAL",
    "CAP_TOOL_USE",
    "CAP_JOB_SUBMISSION",
    # Job Interface (S5.4)
    "JobDispatchResult",
    "dispatch_route",
    # Router (S5.2)
    "DEST_RUNTIME",
    "DEST_S4B",
    "DEST_WORKFLOW",
    "Route",
    "route_message",
    # Supervisor (S5.5)
    "AgentState",
    "LifecycleState",
    "LifecycleEvent",
    # Agent State Store (S5.6)
    "AgentStateStore",
    "StoreError",
]
