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
from src.agent.memory.governance.memory_governance import MemoryGovernance
from src.agent.types.decomposition import DecompositionPlan, DecompositionRequest
from src.agent.types.plan import Plan


@runtime_checkable
class S2Planner(Protocol):
    """S5 → S2: Generate a plan (pure).

    Implementations analyse the goal and available capabilities,
    then produce a structured plan for execution.
    """

    def plan(
        self,
        goal: str,
        subgoal_id: str,
        governance: MemoryGovernance,
        capabilities: Optional[List[DiscoveredSkill]] = None,
    ) -> Plan:
        """Generate a plan for the given goal.

        Args:
            goal: The high-level objective to plan for.
            subgoal_id: The ID of the subgoal this plan belongs to.
            governance: Shared MemoryGovernance instance for cross-store
                consistency checks during planning.
            capabilities: Optional list of discovered skills/tools
                available to the planner.

        Returns:
            A ``Plan`` with intent, target skill, arguments, and reasoning.
        """
        ...


@runtime_checkable
class S2PlanDecomposer(Protocol):
    """S5 → S2: Decompose a task into a dependency-aware DAG of subtasks.

    Implementations analyse the parent task, available agents, and
    constraints, then produce a validated ``DecompositionPlan`` with
    an acyclic DAG where each ``SubtaskSpec.depends_on`` references
    are resolved within the same plan.

    This is the decomposition counterpart to ``S2Planner`` — whereas
    ``S2Planner`` produces a single atomic ``Plan``, ``S2PlanDecomposer``
    produces a multi-step DAG for fan-out execution.
    """

    def decompose(
        self,
        request: DecompositionRequest,
    ) -> DecompositionPlan | None:
        """Decompose *request* into a structured DAG of subtasks.

        Args:
            request: The full decomposition request containing the parent
                task, context, available agents, and constraints.

        Returns:
            A validated ``DecompositionPlan``, or ``None`` if the task
            cannot be meaningfully decomposed (the caller should treat
            it as an atomic job instead).
        """
        ...
