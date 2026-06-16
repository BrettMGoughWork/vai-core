"""
S5 → S2: Planning Protocol
===========================

Defines the contract between the orchestrator (S5) and the planning
stratum (S2).  S5 calls ``plan()`` to generate a structured plan for
a given goal, using discovered capabilities as context.

This is the **only** way S5 interacts with the planner — no direct
imports of S2 implementation details (``SubgoalPlanner``, etc.).

Contract
--------
- ``plan()`` is synchronous and pure (no I/O, no side effects)
- The ``capabilities`` parameter lists the skills/tools available
  for the planner to choose from
- Returns a ``Plan`` with an intent, target skill, arguments, and
  reasoning summary
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from src.capabilities.contracts import DiscoveredSkill
from src.strategy.planning.models.plan import Plan


@runtime_checkable
class S2Planner(Protocol):
    """S5 → S2: Generate a plan (pure).

    Implementations analyse the goal and available capabilities,
    then produce a structured plan for execution.
    """

    def plan(
        self,
        goal: str,
        capabilities: Optional[List[DiscoveredSkill]] = None,
    ) -> Plan:
        """Generate a plan for the given goal.

        Args:
            goal: The high-level objective to plan for.
            capabilities: Optional list of discovered skills/tools
                available to the planner.

        Returns:
            A ``Plan`` with intent, target skill, arguments, and reasoning.
        """
        ...
