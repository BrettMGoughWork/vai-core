"""
AgentPlanner — unified S2 planning entrypoint (Phase 2.15.3).

Wraps SubgoalPlanner and PlanMemory to provide a single
``plan() -> AgentPlan`` API returning the full versioned contract.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import List

from src.strategy.memory.governance.memory_governance import MemoryGovernance
from src.strategy.memory.plan_memory import PlanMemory
from src.strategy.planning.contracts.agent_plan import AgentPlan
from src.strategy.planning.generator.subgoal_planner import SubgoalPlanner
from src.strategy.planning.segments.manager import PlanSegmentManager
from src.strategy.planning.subgoals.manager import SubgoalManager


class AgentPlanner:
    """Unified entrypoint for S2 planning.

    Wraps SubgoalPlanner (LLM-based plan generation) and PlanMemory
    (plan storage/retrieval) to produce a fully-versioned AgentPlan
    contract on every ``plan()`` call.

    Usage::

        def llm_complete(sys: str, usr: str) -> str:
            raw = provider.chat(model="gpt-4", messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": usr},
            ])
            return raw["choices"][0]["message"]["content"]

        planner = AgentPlanner(
            llm_complete=llm_complete,
            plan_memory=plan_memory,
        )
        agent_plan: AgentPlan = planner.plan(
            subgoal_id="sg-1",
            goal="Find and summarise the top 5 AI stories from Hacker News",
            governance=governance,
            timestamp="2025-01-01T00:00:00Z",
            skill_refs=["web_search", "llm_complete"],
        )
    """

    def __init__(
        self,
        llm_complete: Callable[[str, str], str] | None = None,
        plan_memory: PlanMemory | None = None,
        segment_manager: PlanSegmentManager | None = None,
        subgoal_manager: SubgoalManager | None = None,
    ) -> None:
        self._subgoal_planner = SubgoalPlanner(
            llm_complete=llm_complete,
            segment_manager=segment_manager,
        )
        self._subgoal_manager = subgoal_manager
        self._plan_memory = plan_memory

    @property
    def subgoal_manager(self) -> SubgoalManager | None:
        """Access the SubgoalManager if wired, or None."""
        return self._subgoal_manager

    def plan(
        self,
        subgoal_id: str,
        goal: str,
        governance: MemoryGovernance,
        timestamp: str,
        skill_refs: list[str] | None = None,
    ) -> AgentPlan:
        """Generate and hydrate a plan, returning the full AgentPlan contract.

        Delegates to SubgoalPlanner for LLM-based plan generation,
        then reads back the stored Plan + PlanMemoryRecord to
        construct a versioned AgentPlan.

        Args:
            subgoal_id: ID of the subgoal to plan for.
            goal: The goal text to plan against.
            governance: MemoryGovernance for persisting plan artifacts.
            timestamp: ISO timestamp for deterministic IDs.
            skill_refs: Symbolic skill names pre-resolved by S5 (no S3 coupling).

        Returns:
            AgentPlan with full identity, content, and version fields.

        Raises:
            RuntimeError: If the plan was written but cannot be read back.
        """
        # ── 1. Delegate to SubgoalPlanner (LLM → write to governance) ──
        plan_id = self._subgoal_planner.plan_for_subgoal(
            subgoal_id=subgoal_id,
            goal=goal,
            governance=governance,
            timestamp=timestamp,
            skill_refs=skill_refs,
        )

        # ── 2. Read back the stored Plan + record ──
        plan = self._plan_memory.get(plan_id)
        record = self._plan_memory.get_record(plan_id)

        if plan is None or record is None:
            raise RuntimeError(
                f"PlanMemory inconsistency: plan_id={plan_id} "
                f"was written but cannot be read back "
                f"(plan={plan is not None}, record={record is not None})"
            )

        # ── 3. Construct the versioned contract ──
        return AgentPlan.from_plan_and_record(plan, record)
