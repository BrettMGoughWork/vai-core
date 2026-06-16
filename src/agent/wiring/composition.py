"""
Stratum 5 — Composition Root
=============================

Factory functions that wire concrete stratum implementations together
through their protocol interfaces.

All wiring is manual (no DI container).  Each factory accepts the
minimum dependencies and returns a fully-wired instance.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import List, Optional

from src.agent.interfaces.s1_executor import S1Executor
from src.agent.interfaces.s2_planner import S2Planner
from src.agent.interfaces.s3_executor import (
    S3CapabilityDiscovery,
    S3SkillExecutor,
)
from src.agent.interfaces.s4_job_submitter import S4JobSubmitter
from src.agent.wiring.s2_llm_adapter import make_llm_complete

from src.capabilities.contracts import DiscoveredSkill
from src.strategy.planning.models.plan import Plan


def wire_planner(
    s1_executor: S1Executor | None = None,
    s3_discovery: S3CapabilityDiscovery | None = None,
    s3_executor: S3SkillExecutor | None = None,
    s4_job_submitter: S4JobSubmitter | None = None,
) -> S2Planner:
    """Build a fully-wired ``S2Planner`` with an S1-backed LLM callback.

    Args:
        s1_executor:  S1 LLM executor.  When ``None``, the planner will
                      have no ``llm_complete`` callback (falls back to
                      simulation / empty plans).
        s3_discovery: (reserved) S3 capability discovery for skills.
        s3_executor:  (reserved) S3 skill executor for plans.
        s4_job_submitter: (reserved) S4 job submitter for durable steps.

    Returns:
        An ``S2Planner`` protocol implementation wrapping ``AgentPlanner``.
    """

    class _WiredPlanner:
        """Adapter that wires S1 → S2 ``llm_complete`` via protocol."""

        def __init__(self) -> None:
            from src.strategy.planning.agent_planner import AgentPlanner

            llm_complete = (
                make_llm_complete(s1_executor) if s1_executor else None
            )
            self._inner = AgentPlanner(llm_complete=llm_complete)

        def plan(
            self,
            goal: str,
            capabilities: Optional[List[DiscoveredSkill]] = None,
        ) -> Plan:
            """Generate a plan for *goal* using the wired S1 backend."""
            # AgentPlanner.plan() requires subgoal_id, governance, timestamp
            # — for now we provide sensible defaults so the wiring can be
            # tested end-to-end.  A proper S2Planner contract that maps
            # cleanly to AgentPlanner will be defined in a follow-up phase.
            from datetime import datetime, timezone

            from src.strategy.memory.governance.memory_governance import (
                MemoryGovernance,
            )
            from src.strategy.memory.plan_memory import PlanMemory

            subgoal_id: str = f"sg-{hash(goal) & 0xFFFFFFFF:08x}"
            now = datetime.now(timezone.utc).isoformat()

            governance = MemoryGovernance(
                plan_memory=PlanMemory(),
            )

            skill_refs: list[str] | None = (
                [s.name for s in capabilities] if capabilities else None
            )

            agent_plan = self._inner.plan(
                subgoal_id=subgoal_id,
                goal=goal,
                governance=governance,
                timestamp=now,
                skill_refs=skill_refs,
            )

            # AgentPlan → Plan conversion for protocol conformance
            plan_content = getattr(agent_plan, "plan", None)
            if plan_content is not None:
                return plan_content
            return Plan(
                intent=goal,
                target_skill="",
                arguments={},
                reasoning="Plan generated via wired S1 backend",
            )

    return _WiredPlanner()


__all__ = [
    "wire_planner",
]
