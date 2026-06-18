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
            capabilities: Optional[List[DiscoveredSkill]] = None,
        ) -> SimpleNamespace:
            """Generate a plan for *goal* using the wired S1 backend."""
            # AgentPlanner.plan() requires subgoal_id, governance, timestamp
            # — for now we provide sensible defaults so the wiring can be
            # tested end-to-end.  A proper S2Planner contract that maps
            # cleanly to AgentPlanner will be defined in a follow-up phase.
            from datetime import datetime, timezone

            from src.strategy.memory.governance.memory_governance import (
                MemoryGovernance,
            )
            from src.strategy.memory.subgoal_memory import SubgoalMemory
            from src.strategy.memory.segment_memory import SegmentMemory
            from src.strategy.memory.drift_memory import DriftMemory
            from src.strategy.types.subgoal import Subgoal

            subgoal_id: str = f"sg-{hash(goal) & 0xFFFFFFFF:08x}"
            now = datetime.now(timezone.utc).isoformat()
            now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)

            subgoal_memory = SubgoalMemory()
            seg_memory = SegmentMemory()
            plan_memory = self._plan_memory
            drift_memory = DriftMemory()

            # Seed a subgoal so plan consistency checks pass
            subgoal_memory.put(Subgoal(
                subgoal_id=subgoal_id,
                goal=goal,
                context={},
                metadata={},
                created_at=now_ts,
            ))

            governance = MemoryGovernance(
                subgoal_memory=subgoal_memory,
                segment_memory=seg_memory,
                plan_memory=plan_memory,
                drift_memory=drift_memory,
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

            # ── Reconstruct step data from the stored segment ──
            steps: List[Dict[str, Any]] = []
            if agent_plan.segments:
                segment_id = agent_plan.segments[0]
                segment = seg_memory.get(segment_id)
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
