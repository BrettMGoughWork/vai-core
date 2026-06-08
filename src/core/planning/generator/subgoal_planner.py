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
from src.stratum2.s3_adapter import S3Adapter, S2DiscoveryQuery

_SYSTEM_PROMPT: str = (
    "You are a planning assistant. Given a user goal, produce a plan in JSON format.\n"
    "\n"
    "Return ONLY a JSON object with this exact structure:\n"
    "{\n"
    '  "plan": {\n'
    '    "subgoal": "<a concise re-statement of the goal>",\n'
    '    "steps": [\n'
    '      {"id": "<step-id>", "description": "<what to do>", "capability": "<capability name>"}\n'
    "    ]\n"
    "  }\n"
    "}\n"
    "\n"
    'Rules:\n'
    '- "subgoal" must be a concise re-statement of the user goal (1 sentence).\n'
    '- "steps" must contain 1-3 step objects.\n'
    '- Each step must have "id", "description", and "capability" fields.\n'
    '- "capability" should be a short identifier like "echo", "print", "parse", etc.\n'
    '- Return ONLY the JSON object, no other text, no markdown fences.'
)


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

    def __init__(
        self,
        llm: ChatProvider,
        model: str = "mock",
        s3_adapter: S3Adapter | None = None,
    ) -> None:
        self._llm = llm
        self._model = model
        self._s3_adapter = s3_adapter

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
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": goal},
            ],
        )
        content: str = raw["choices"][0]["message"]["content"]
        # Strip markdown code fences if the LLM wraps the JSON in them
        content = content.strip()
        if content.startswith("```"):
            # Remove ```json or ``` prefix and trailing ```
            content = content.split("\n", 1)[-1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        plan_dict: Dict[str, Any] = json.loads(content)

        # Parse the LLM response shape: {"plan": {"subgoal": str, "steps": [{id, description, capability}]}}
        plan_body = plan_dict["plan"]
        subgoal_text: str = plan_body["subgoal"]
        steps_list: List[Dict[str, Any]] = plan_body["steps"]

        # All step descriptions become a single PlanSegment's steps list.
        step_descriptions = [s["description"] for s in steps_list]
        step_capabilities = [s["capability"] for s in steps_list if s.get("capability")]
        step_ids = [s["id"] for s in steps_list]

        # --- skill discovery via S3 adapter (Phase 3.8.6) ---
        discovered_skill_names: list[str] = []
        if self._s3_adapter is not None:
            discovery = self._s3_adapter.discover_skills(
                S2DiscoveryQuery(query=subgoal_text, limit=10)
            )
            discovered_skill_names = [sk.name for sk in discovery.skills]

        # 1. Write segment first — plan governance validates segment IDs exist.
        segment = PlanSegment(
            subgoal_id=subgoal_id,
            steps=step_descriptions,
            context={"capabilities": step_capabilities, "step_ids": step_ids},
            metadata={},
            skills=discovered_skill_names,
            created_at=timestamp,  # deterministic: same timestamp → same segment_id
        )
        governance.put_segment(segment)
        segment_ids = [segment.segment_id]

        # 2. Write the plan (references segment IDs persisted above).
        # targetskillid = first discovered skill if available, else first
        # LLM capability, falling back to "unknown".
        if discovered_skill_names:
            targetskillid = discovered_skill_names[0]
        elif step_capabilities:
            targetskillid = step_capabilities[0]
        else:
            targetskillid = "unknown"
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
