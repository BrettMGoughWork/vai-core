"""
SubgoalPlanner — calls a ChatProvider to generate a Plan and PlanSegments for a subgoal.

Used by AgentLoopV2 when an active subgoal has no plan in PlanMemory.
All hydration and decomposition use existing types and memory substrates; no new abstractions.

Response parsing expects an OpenAI-shaped chat completion
(choices[0]["message"]["content"] must be a JSON string conforming to MOCK_PLAN_RESPONSE).

To switch to a live LLM, pass any ChatProvider at construction:
    SubgoalPlanner(llm=llm_factory.create("openai", model="gpt-4"), model="gpt-4")
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from src.core.llm.providers._base import ChatProvider
from src.core.memory.governance.memory_governance import MemoryGovernance
from src.core.planning.models.plan import Plan
from src.core.types.hashing import stable_hash
from src.core.types.plan_segment import PlanSegment


class SubgoalPlanner:
    """
    Stratum-2 planning component.

    Calls a ChatProvider to generate a Plan and PlanSegments for a subgoal
    that has no plan in PlanMemory.  All writes go through MemoryGovernance
    (validated, consistency-checked, governed).

    Write order: segments are written before the plan that references them,
    satisfying the MemoryGovernance cross-store consistency constraint.

    Passing created_at=timestamp makes segment_ids and plan_id deterministic
    within a cycle — retried writes within the same cycle are idempotent.
    """

    def __init__(self, llm: ChatProvider, model: str = "mock") -> None:
        self._llm = llm
        self._model = model

    def plan_for_subgoal(
        self,
        subgoal_id: str,
        goal: str,
        governance: MemoryGovernance,
        timestamp: str,
    ) -> str:
        """
        Generate and hydrate a plan for the given subgoal.

        1. Call the LLM with the subgoal goal as the prompt.
        2. Parse the JSON plan response.
        3. Write PlanSegments to SegmentMemory via governance (segments first).
        4. Write the Plan to PlanMemory via governance (references segment IDs).

        Returns the plan_id of the hydrated plan.
        Raises on LLM failure, JSON parse error, or governance rejection.
        """
        raw = self._llm.chat(
            model=self._model,
            messages=[{"role": "user", "content": goal}],
        )
        plan_dict: Dict[str, Any] = json.loads(raw["choices"][0]["message"]["content"])

        # Parse the LLM response shape: {"plan": {"subgoal": str, "steps": [{id, description, capability}]}}
        plan_body = plan_dict["plan"]
        subgoal_text: str = plan_body["subgoal"]
        steps_list: List[Dict[str, Any]] = plan_body["steps"]

        # All step descriptions become a single PlanSegment's steps list.
        step_descriptions = [s["description"] for s in steps_list]
        step_capabilities = [s["capability"] for s in steps_list if s.get("capability")]
        step_ids = [s["id"] for s in steps_list]

        # 1. Write segment first — plan governance validates segment IDs exist.
        segment = PlanSegment(
            subgoal_id=subgoal_id,
            steps=step_descriptions,
            context={"capabilities": step_capabilities, "step_ids": step_ids},
            metadata={},
            created_at=timestamp,  # deterministic: same timestamp → same segment_id
        )
        governance.put_segment(segment)
        segment_ids = [segment.segment_id]

        # 2. Write the plan (references segment IDs persisted above).
        # targetskillid = capability of the first step; intent = the subgoal text.
        targetskillid = step_capabilities[0] if step_capabilities else "unknown"
        plan = Plan(
            intent=subgoal_text,
            targetskillid=targetskillid,
            arguments={},
            reasoning_summary=f"Steps: {', '.join(step_ids)}",
        )
        plan_id = stable_hash({
            "subgoal_id": subgoal_id,
            "intent": plan.intent,
            "targetskillid": plan.targetskillid,
            "timestamp": timestamp,
        })
        governance.put_plan(
            plan=plan,
            plan_id=plan_id,
            subgoal_id=subgoal_id,
            segments=segment_ids,
            created_at=timestamp,
        )
        return plan_id
