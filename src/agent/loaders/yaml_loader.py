"""
YAML Agent Manifest Loader
===========================

Reads declarative agent definitions from YAML files and registers
them into an ``AgentRegistry``.

Two load modes are supported:

1. Single-file manifest (``load_agent_manifest``): reads a top-level
   ``agents`` list from one YAML file.

2. Directory scan (``load_agents_from_directory``): scans a directory
   for individual ``*.yaml`` / ``*.yml`` files, each containing one
   agent definition (no wrapping ``agents`` key).  This mirrors the
   ``load_workflows_from_yaml`` pattern.

Single-file YAML format::

    agents:
      - agent_id: my-agent
        name: My Agent
        description: Does something useful
        version: 1.0.0
        provenance: built-in           # built-in | user-defined | system
        capabilities: [conversational, tool_use]
        persona: "Role description for agent-selection matching"
        defer_to:                     # optional list of agents this agent can defer to
          - specialist-agent
        inputs: [text, markdown]
        outputs: [text, json]
        constraints:
          max_tokens: 4096
          timeout_ms: 30000
          sandbox: none                # none | process | container

Per-file format (no ``agents`` wrapping key)::

    agent_id: my-agent
    name: My Agent
    description: Does something useful
    # … same fields as above, but at the top level
"""

from __future__ import annotations

from pathlib import Path
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
        persona=entry.get("persona", ""),
        skills=entry.get("skills", []),
        tools=entry.get("tools", []),
        workflows=entry.get("workflows", []),
        patterns=entry.get("patterns", []),
        defer_to=entry.get("defer_to", []),
        inputs=entry.get("inputs", []),
        outputs=entry.get("outputs", []),
        constraints=constraints,
    )


def load_agents_from_directory(
    registry: AgentRegistry,
    directory: str | Path,
) -> List[AgentHandle]:
    """Scan *directory* for ``*.yaml`` / ``*.yml`` files, each containing
    a single agent definition (no wrapping ``agents`` key), and register
    each into *registry*.

    Skips non-existent directories and files that fail to parse or validate,
    printing warnings to stderr so the caller knows an agent was skipped.
    """
    root = Path(directory)
    if not root.is_dir():
        return []

    found: List[AgentHandle] = []
    for yaml_path in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")):
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            if not isinstance(raw, dict):
                print(
                    f"[agent-loader] skipping {yaml_path.name}: "
                    f"not a mapping"
                )
                continue
            metadata = _parse_entry(raw)
            handle = registry.register_agent(metadata)
            found.append(handle)
        except (AgentRegistryError, ValueError, TypeError, KeyError) as exc:
            print(
                f"[agent-loader] skipping {yaml_path.name}: {exc}"
            )
    return found
