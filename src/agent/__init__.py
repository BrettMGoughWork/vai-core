"""  
Stratum 5 — Agent Layer  
========================  

The S5 conversational layer is the highest stratum in the runtime.  
It routes incoming messages to the appropriate destination via the  
Agent Router (S5.2) — Runtime (LLM conversations), Workflow Engine
(multi-step / orchestration), or S4B (capability execution).

Sub-modules  
-----------  
contracts (S5.0)  
    AgentMessage, AgentResponse types and validation.  
registry (S5.1)  
    Agent identity, metadata, capability declarations, and static  
    agent registry.  
activation (S5.2)  
    Activation envelope, context injection, capability resolution,  
    and the ``activate_agent()`` entry point.  
router (S5.2)  
    Pattern-based message router — inspects incoming messages and  
    determines destination (Runtime / Workflow / S4B).

Exports  
-------  
All public types and functions from each sub-module are re-exported  
here for convenience.  
"""  

from src.agent.activation import (  
    CHANNEL_CLI,  
    CHANNEL_HTTP,  
    CHANNEL_TUI,  
    CHANNEL_WEB,  
    CHANNEL_SYSTEM,  
    VALID_CHANNELS,  
    ACTIVATION_AUTHORIZED_CHANNELS,  
    ActivationContext,  
    ActivatedAgentContext,  
    ActivationEnvelope,  
    ActivationError,  
    UnauthorizedChannelError,  
    activate_agent,  
    resolve_capabilities,  
)  
from src.agent.contracts import (  
    S5_CONTRACT_VERSION,  
    AgentMessage,  
    AgentResponse,  
)  
from src.agent.router import (  
    DEST_RUNTIME,  
    DEST_S4B,  
    DEST_WORKFLOW,
    Route,  
    route_message,  
)  
from src.agent.interfaces.agent_state import (
    AgentState,
    LifecycleEvent,
    LifecycleState,
)
from src.agent.interfaces.agent_state_store import (
    AgentStateStore,
    StoreError,
)
from src.agent.supervisor import (
    AgentInTerminalStateError,
    AgentNotActiveError,
    AgentNotSuspendedError,
    Supervisor,
    SupervisorError,
)
from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
from src.agent.adapters.file_agent_state_store import FileAgentStateStore
from src.agent.adapters.sqlite_agent_state_store import SQLiteAgentStateStore
from src.agent.loaders.yaml_loader import (
    load_agent_manifest,
)
from src.agent.registry import (
    AGENT_REGISTRY_VERSION,
    CAP_ANALYSIS,
    CAP_CONVERSATIONAL,
    CAP_JOB_SUBMISSION,
    CAP_PLANNING,
    CAP_ROUTING,
    CAP_SUMMARIZATION,
    CAP_TOOL_USE,
    PROVENANCE_BUILTIN,
    PROVENANCE_SYSTEM,
    PROVENANCE_USER_DEFINED,
    SANDBOX_CONTAINER,
    SANDBOX_NONE,
    SANDBOX_PROCESS,
    VALID_CAPABILITIES,
    VALID_PROVENANCES,
    VALID_SANDBOX_LEVELS,
    AgentConstraints,
    AgentHandle,
    AgentIdentity,
    AgentMetadata,
    AgentNotFoundError,
    AgentRegistry,
    AgentRegistryError,
    DuplicateAgentError,
    UnknownCapabilityError,
)

__all__ = [
    # ── Contracts (S5.0) ──────────────────────────────────────────────
    "S5_CONTRACT_VERSION",
    "AgentMessage",
    "AgentResponse",
    # ── Registry (S5.1) ───────────────────────────────────────────────
    "AGENT_REGISTRY_VERSION",
    "CAP_ANALYSIS",
    "CAP_CONVERSATIONAL",
    "CAP_JOB_SUBMISSION",
    "CAP_PLANNING",
    "CAP_ROUTING",
    "CAP_SUMMARIZATION",
    "CAP_TOOL_USE",
    "PROVENANCE_BUILTIN",
    "PROVENANCE_SYSTEM",
    "PROVENANCE_USER_DEFINED",
    "SANDBOX_CONTAINER",
    "SANDBOX_NONE",
    "SANDBOX_PROCESS",
    "VALID_CAPABILITIES",
    "VALID_PROVENANCES",
    "VALID_SANDBOX_LEVELS",
    "AgentConstraints",
    "AgentHandle",
    "AgentIdentity",
    "AgentMetadata",
    "AgentNotFoundError",
    "AgentRegistry",
    "AgentRegistryError",
    "DuplicateAgentError",
    "UnknownCapabilityError",
    # ── Activation (S5.2) ─────────────────────────────────────────────
    "CHANNEL_CLI",
    "CHANNEL_HTTP",
    "CHANNEL_TUI",
    "CHANNEL_WEB",
    "CHANNEL_SYSTEM",
    "VALID_CHANNELS",
    "ACTIVATION_AUTHORIZED_CHANNELS",
    "ActivationContext",
    "ActivatedAgentContext",
    "ActivationEnvelope",
    "ActivationError",
    "UnauthorizedChannelError",
    "activate_agent",
    "resolve_capabilities",
    # ── Router (S5.2) ─────────────────────────────────────────────────
    "DEST_RUNTIME",
    "DEST_S4B",
    "DEST_WORKFLOW",
    "Route",
    "route_message",
    # ── Supervisor (S5.5) ──────────────────────────────────────────────
    "AgentInTerminalStateError",
    "AgentNotActiveError",
    "AgentNotSuspendedError",
    "Supervisor",
    "SupervisorError",
    # ── Agent State Store (S5.6) ───────────────────────────────────────
    "AgentState",
    "AgentStateStore",
    "FileAgentStateStore",
    "LifecycleEvent",
    "LifecycleState",
    "MemoryAgentStateStore",
    "SQLiteAgentStateStore",
    "StoreError",
]
