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
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from src.agent.interfaces.s1_executor import S1Executor
from src.agent.interfaces.s2_planner import S2Planner
from src.strategy.memory.governance.memory_governance import MemoryGovernance
from src.agent.interfaces.s3_executor import (
    S3CapabilityDiscovery,
    S3SkillExecutor,
)
from src.agent.interfaces.s4_job_submitter import S4JobSubmitter
from src.agent.wiring.s2_llm_adapter import make_llm_complete

from src.capabilities.contracts import DiscoveredSkill


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
            from src.strategy.memory.plan_memory import PlanMemory

            llm_complete = (
                make_llm_complete(s1_executor) if s1_executor else None
            )
            self._plan_memory = PlanMemory()
            self._inner = AgentPlanner(
                llm_complete=llm_complete,
                plan_memory=self._plan_memory,
            )

        def plan(
            self,
            goal: str,
            subgoal_id: str,
            governance: MemoryGovernance,
            capabilities: Optional[List[DiscoveredSkill]] = None,
        ) -> SimpleNamespace:
            """Generate a plan for *goal* using the wired S1 backend.

            The ``subgoal_id`` and ``governance`` are provided by the caller
            (StrategyRouter), which creates the subgoal in shared governance
            before invoking the planner.  This ensures cross-store consistency
            is maintained across the full S5→S2 planning pipeline.
            """
            from datetime import datetime, timezone

            if subgoal_id is None or governance is None:
                raise ValueError("subgoal_id and governance are required")

            now = datetime.now(timezone.utc).isoformat()

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

            # ── Reconstruct step data from the stored segment ──
            steps: List[Dict[str, Any]] = []
            if agent_plan.segments:
                segment_id = agent_plan.segments[0]
                segment = governance.get_segment(segment_id)
                if segment is not None:
                    cap_list: List[str] = segment.context.get("capabilities", [])
                    id_list: List[str] = segment.context.get("step_ids", [])
                    input_list: List[Dict[str, Any]] = segment.context.get("step_inputs", [])
                    desc_list: List[str] = segment.steps

                    for i, step_id in enumerate(id_list):
                        steps.append({
                            "id": step_id,
                            "description": desc_list[i] if i < len(desc_list) else "",
                            "skill_ref": cap_list[i] if i < len(cap_list) else "",
                            "inputs": input_list[i] if i < len(input_list) else {},
                        })

            return SimpleNamespace(
                plan_id=agent_plan.plan_id,
                steps=[SimpleNamespace(**s) for s in steps],
                intent=agent_plan.intent,
                reasoning_summary=agent_plan.reasoning_summary,
                segments=agent_plan.segments,
            )

    return _WiredPlanner()


__all__ = [
    "wire_planner",
]
