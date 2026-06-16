"""
S5 → S3: Skill Execution & Discovery Protocols
===============================================

Defines the contract between the orchestrator (S5) and the capability
stratum (S3).  Two orthogonal concerns:

1. **Discovery** — S5 asks S3 what skills/tools are available for a
   given context.
2. **Execution** — S5 asks S3 to execute a specific skill directly
   (no S4 mediation unless durability is required).

This is the **only** way S5 interacts with S3 — no direct imports of
S3 implementation details (``SkillRunner``, ``CapabilityEngine``, etc.).

Contracts
---------
- ``S3CapabilityDiscovery.discover()`` — synchronous, returns ranked
  list of ``DiscoveredSkill`` matching the query
- ``S3SkillExecutor.execute()`` — synchronous, returns ``SkillResult``
  with output or error
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable

from src.capabilities.contracts import DiscoveredSkill, SkillResult


@runtime_checkable
class S3CapabilityDiscovery(Protocol):
    """S5 → S3: Discover available capabilities.

    Implementations query the capability registry and return ranked
    skill descriptors matching the given query.
    """

    def discover(
        self,
        query: str,
        limit: int = 10,
    ) -> List[DiscoveredSkill]:
        """Discover skills matching a query.

        Args:
            query: Natural-language or keyword query describing the
                   capability needed.
            limit: Maximum number of results to return.

        Returns:
            Ranked list of ``DiscoveredSkill`` matching the query.
        """
        ...


@runtime_checkable
class S3SkillExecutor(Protocol):
    """S5 → S3: Execute a skill directly (no S4).

    Implementations invoke the named skill's primitive(s) with the
    provided arguments and return a ``SkillResult``.
    """

    def execute(
        self,
        skill_name: str,
        arguments: Dict[str, Any],
    ) -> SkillResult:
        """Execute a skill by name.

        Args:
            skill_name: The name of the skill to execute (must match a
                        registered skill's manifest name).
            arguments: Key-value arguments expected by the skill's
                       input schema.

        Returns:
            A ``SkillResult`` with output (on success) or error.
        """
        ...
