"""
YAML Agent Manifest Loader
===========================

Reads a declarative ``agents.yaml`` file and registers every agent
definition into an ``AgentRegistry``.

Usage::

    from src.agent import AgentRegistry, load_agent_manifest

    registry = AgentRegistry()
    handles = load_agent_manifest(registry, "config/agents.yaml")

YAML format::

    agents:
      - agent_id: my-agent
        name: My Agent
        description: Does something useful
        version: 1.0.0
        provenance: built-in           # built-in | user-defined | system
        capabilities: [conversational, tool_use]
        inputs: [text, markdown]
        outputs: [text, json]
        constraints:
          max_tokens: 4096
          timeout_ms: 30000
          sandbox: none                # none | process | container
"""

from __future__ import annotations

from typing import List

import yaml

from src.agent.registry import (
    AgentConstraints,
    AgentHandle,
    AgentIdentity,
    AgentMetadata,
    AgentRegistry,
    AgentRegistryError,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_agent_manifest(
    registry: AgentRegistry,
    path: str,
) -> List[AgentHandle]:
    """Load agent definitions from a YAML manifest file.

    Each entry under the top-level ``agents`` key is parsed into an
    ``AgentMetadata`` instance and registered into *registry*.

    Parameters
    ----------
    registry:
        An ``AgentRegistry`` instance — must be mutable (not frozen).
    path:
        Filesystem path to the YAML manifest file.

    Returns
    -------
    list[AgentHandle]:
        One handle per successfully registered agent.

    Raises
    ------
    FileNotFoundError:
        *path* does not exist.
    yaml.YAMLError:
        *path* is not valid YAML.
    AgentRegistryError:
        A definition failed validation or duplicated an existing agent_id.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict) or "agents" not in data:
        raise AgentRegistryError(
            f"agent manifest {path!r} must contain a top-level 'agents' list"
        )

    agents = data["agents"]
    if not isinstance(agents, list):
        raise AgentRegistryError(
            f"agent manifest {path!r}: 'agents' must be a list"
        )

    handles: List[AgentHandle] = []

    for i, entry in enumerate(agents):
        if not isinstance(entry, dict):
            raise AgentRegistryError(
                f"agent manifest {path!r}: entry at index {i} must be a mapping"
            )

        agent_id = entry.get("agent_id", f"<index {i}>")
        try:
            metadata = _parse_entry(entry)
            handle = registry.register_agent(metadata)
            handles.append(handle)
        except (AgentRegistryError, ValueError, TypeError) as exc:
            raise AgentRegistryError(
                f"agent {agent_id!r} in {path!r}: {exc}"
            ) from exc

    return handles


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_entry(entry: dict) -> AgentMetadata:
    """Parse a single YAML agent entry into an ``AgentMetadata`` instance."""
    identity = AgentIdentity(
        agent_id=entry["agent_id"],
        name=entry.get("name", entry["agent_id"]),
        description=entry.get("description", ""),
        version=entry.get("version", "1.0.0"),
        provenance=entry.get("provenance", "built-in"),
    )

    constraints_dict = entry.get("constraints", {})
    constraints = AgentConstraints(
        max_tokens=constraints_dict.get("max_tokens", 0),
        max_iterations=constraints_dict.get("max_iterations", 10),
        timeout_ms=constraints_dict.get("timeout_ms", 0),
        sandbox=constraints_dict.get("sandbox", "none"),
    )

    return AgentMetadata(
        identity=identity,
        capabilities=entry.get("capabilities", []),
        inputs=entry.get("inputs", []),
        outputs=entry.get("outputs", []),
        constraints=constraints,
    )
