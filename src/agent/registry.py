"""
Phase 5.1 — Agent Registry & Identity
=======================================

Structured registry of all agents, their metadata, capabilities, and
identity information.  The registry is a static, declarative source of
truth — populated at startup, read‑only at runtime.

No planning, no execution, no dispatch, no S4 job submission.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_REGISTRY_VERSION = "1.0"
"""Current version of the agent registry schema."""

# Valid provenance values
PROVENANCE_BUILTIN = "built-in"
PROVENANCE_USER_DEFINED = "user-defined"
PROVENANCE_SYSTEM = "system"
VALID_PROVENANCES = frozenset({
    PROVENANCE_BUILTIN,
    PROVENANCE_USER_DEFINED,
    PROVENANCE_SYSTEM,
})

# Valid sandbox levels
SANDBOX_NONE = "none"
SANDBOX_PROCESS = "process"
SANDBOX_CONTAINER = "container"
VALID_SANDBOX_LEVELS = frozenset({SANDBOX_NONE, SANDBOX_PROCESS, SANDBOX_CONTAINER})



# ---------------------------------------------------------------------------
# AgentIdentity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentIdentity:
    """Unique identity for an agent.

    Fields
    ------
    agent_id:
        Stable, unique identifier for the agent.
    name:
        Human‑readable name.
    description:
        Short description of the agent's purpose.
    version:
        Semver version string.
    provenance:
        Origin of the agent — one of VALID_PROVENANCES.
    """

    agent_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    provenance: str = PROVENANCE_BUILTIN

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("agent_id must be non-empty")
        if not self.name:
            raise ValueError("name must be non-empty")
        if not self.version:
            raise ValueError("version must be non-empty")
        if self.provenance not in VALID_PROVENANCES:
            raise ValueError(
                f"provenance must be one of {sorted(VALID_PROVENANCES)}, "
                f"got {self.provenance!r}"
            )
        _validate_semver(self.version)


# ---------------------------------------------------------------------------
# AgentConstraints
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentConstraints:
    """Resource and safety constraints for an agent.

    Fields
    ------
    max_tokens:
        Maximum token budget per response.  0 means unlimited.
    max_iterations:
        Maximum cognitive-loop iterations per activation.  0 means unlimited.
    timeout_ms:
        Maximum wall-clock time in milliseconds.  0 means unlimited.
    sandbox:
        Isolation level — one of VALID_SANDBOX_LEVELS.
    """

    max_tokens: int = 0
    max_iterations: int = 10
    timeout_ms: int = 0
    sandbox: str = SANDBOX_NONE

    def __post_init__(self) -> None:
        if self.max_tokens < 0:
            raise ValueError(f"max_tokens must be >= 0, got {self.max_tokens}")
        if self.max_iterations < 0:
            raise ValueError(
                f"max_iterations must be >= 0, got {self.max_iterations}"
            )
        if self.timeout_ms < 0:
            raise ValueError(f"timeout_ms must be >= 0, got {self.timeout_ms}")
        if self.sandbox not in VALID_SANDBOX_LEVELS:
            raise ValueError(
                f"sandbox must be one of {sorted(VALID_SANDBOX_LEVELS)}, "
                f"got {self.sandbox!r}"
            )


# ---------------------------------------------------------------------------
# AgentMetadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentMetadata:
    """Complete metadata declaration for an agent.

    Fields
    ------
    identity:
        The agent's unique identity.
    persona:
        Human‑readable persona / role description for agent selection matching.
        Used by the ``AgentSelectionStrategy`` when a workflow step specifies
        an ``agent_profile`` in its config.
    skills:
        Explicit list of skill names the agent has access to.
    workflows:
        Explicit list of workflow IDs the agent has access to.
    inputs:
        Input types the agent accepts.
    outputs:
        Output types the agent produces.
    constraints:
        Resource and safety constraints.
    """

    identity: AgentIdentity
    persona: str = ""
    skills: List[str] = field(default_factory=list)
    workflows: List[str] = field(default_factory=list)
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    constraints: AgentConstraints = field(default_factory=AgentConstraints)

    def __post_init__(self) -> None:
        if not isinstance(self.skills, list):
            raise ValueError("skills must be a list")
        if not isinstance(self.workflows, list):
            raise ValueError("workflows must be a list")
        if not isinstance(self.inputs, list):
            raise ValueError("inputs must be a list")
        if not isinstance(self.outputs, list):
            raise ValueError("outputs must be a list")


# ---------------------------------------------------------------------------
# AgentHandle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentHandle:
    """Lightweight handle returned on agent registration.

    The handle is a value object — it carries the agent_id and a
    reference to the registered metadata for discovery lookups.
    """

    agent_id: str
    metadata: AgentMetadata = field(repr=False)


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------


class AgentRegistryError(Exception):
    """Base error for registry operations."""


class DuplicateAgentError(AgentRegistryError):
    """Raised when registering an agent with a duplicate ID."""


class AgentNotFoundError(AgentRegistryError):
    """Raised when a lookup by agent_id fails."""


class AgentRegistry:
    """Static registry of agents.

    Populated at startup via ``register_agent``.  After startup the
    registry is read‑only — no mutation, no dynamic registration.

    All discovery methods are deterministic and side‑effect free.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, AgentMetadata] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_agent(self, metadata: AgentMetadata) -> AgentHandle:
        """Register an agent.

        Validates metadata, rejects duplicate IDs.
        Registration is idempotent — calling with the
        same metadata is a no‑op; calling with different metadata for
        an existing ID raises ``DuplicateAgentError``.
        """
        if not isinstance(metadata, AgentMetadata):
            raise TypeError("metadata must be an AgentMetadata instance")

        existing = self._agents.get(metadata.identity.agent_id)
        if existing is not None:
            if existing == metadata:
                return AgentHandle(
                    agent_id=metadata.identity.agent_id,
                    metadata=metadata,
                )
            raise DuplicateAgentError(
                f"agent {metadata.identity.agent_id!r} already registered"
            )

        self._agents[metadata.identity.agent_id] = metadata
        return AgentHandle(
            agent_id=metadata.identity.agent_id,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Discovery (read‑only)
    # ------------------------------------------------------------------

    def get_agent(self, agent_id: str) -> AgentMetadata:
        """Look up an agent by its ID.

        Raises ``AgentNotFoundError`` if the agent does not exist.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"agent {agent_id!r} not found")
        return agent

    def list_agents(self) -> List[AgentMetadata]:
        """Return metadata for every registered agent."""
        return list(self._agents.values())

    def find_agents_by_skill(self, skill_name: str) -> List[AgentMetadata]:
        """Return all agents that have *skill_name* in their skills list."""
        return [
            a for a in self._agents.values()
            if skill_name in a.skills
        ]

    def find_agents_by_workflow(self, workflow_id: str) -> List[AgentMetadata]:
        """Return all agents that have *workflow_id* in their workflows list."""
        return [
            a for a in self._agents.values()
            if workflow_id in a.workflows
        ]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def agent_count(self) -> int:
        """Number of registered agents."""
        return len(self._agents)

    def has_agent(self, agent_id: str) -> bool:
        """Check whether an agent ID is registered."""
        return agent_id in self._agents


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

SEMVER_REQUIRED_PARTS = 3


def _validate_semver(version: str) -> None:
    """Validate a semver string (MAJOR.MINOR.PATCH)."""
    if not version or not isinstance(version, str):
        raise ValueError(f"version must be a non-empty string, got {version!r}")
    parts = version.split(".")
    if len(parts) < SEMVER_REQUIRED_PARTS:
        raise ValueError(
            f"version must be MAJOR.MINOR.PATCH, got {version!r}"
        )
    for part in parts[:SEMVER_REQUIRED_PARTS]:
        try:
            int(part)
        except ValueError:
            raise ValueError(
                f"version must be MAJOR.MINOR.PATCH, "
                f"non-numeric component in {version!r}"
            )
