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
from src.stratum2.s3_adapter import S3Adapter, S2DiscoveryQuery, S2DiscoveredSkill

def _build_system_prompt(skills: list[S2DiscoveredSkill] | None = None) -> str:
    """Build a dynamic system prompt, optionally listing available skills and their input schemas.

    When *skills* are provided (Phase 3.18.3 schema‑aware planning), each skill's name,
    description, and required inputs are injected so the LLM can produce valid per‑step
    ``inputs`` dictionaries.
    """
    skill_block = ""
    if skills:
        lines: list[str] = ["AVAILABLE CAPABILITIES:"]
        for sk in skills:
            schema_desc = _describe_schema(sk.input_schema)
            lines.append(f"- {sk.name}: {sk.description}. Inputs: {schema_desc}")
        skill_block = "\n".join(lines) + "\n\n"

    return (
        "You are a planning assistant. Given a user goal, produce a plan in JSON format.\n"
        "\n"
        + skill_block +
        "Return ONLY a JSON object with this exact structure:\n"
        "{\n"
        '  "plan": {\n'
        '    "subgoal": "<a concise re-statement of the goal>",\n'
        '    "arguments": {},\n'
        '    "steps": [\n'
        '      {\n'
        '        "id": "<step-id>",\n'
        '        "description": "<what to do>",\n'
        '        "capability": "<capability name from the list above>",\n'
        '        "inputs": {"<param>": "<value>"}\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
        "\n"
        "Rules:\n"
        '- "subgoal" must be a concise re-statement of the user goal (1 sentence).\n'
        '- "arguments" is a JSON object of key-value pairs (top-level fallback).\n'
        '- "steps" must contain 1-3 step objects.\n'
        '- Each step must have "id", "description", "capability", and "inputs" fields.\n'
        '- "capability" MUST be the exact name from the AVAILABLE CAPABILITIES list.\n'
        '- "inputs" MUST include all required parameters for the chosen capability.\n'
        '- Infer "inputs" values from the user\'s goal text. Example: if the user says "echo hello world" and the capability requires a parameter named "value", then inputs = {"value": "hello world"}. If the user says "ping example.com" and the capability requires "host", then inputs = {"host": "example.com"}.\n'
        '- Return ONLY the JSON object, no other text, no markdown fences.'
    )


def _describe_schema(input_schema: dict[str, Any] | None) -> str:
    """Convert a skill input schema to a compact human-readable description.

    Handles both formats:
    1. JSON Schema format: {"required": [...], "properties": {...}}
    2. Flat format (from skill manifests): {"param": {"type": "str", "required": True}, ...}
    """
    if not input_schema:
        return "{}"
    # ── Format 1: JSON Schema ──
    if "properties" in input_schema:
        required: set[str] = set(input_schema.get("required", []))
        properties: dict[str, Any] = input_schema["properties"]
        if not properties:
            return "{}"
        parts: list[str] = []
        for prop_name, prop_def in properties.items():
            prop_type = prop_def.get("type", "string") if isinstance(prop_def, dict) else "string"
            req = " (required)" if prop_name in required else " (optional)"
            parts.append(f'"{prop_name}": {prop_type}{req}')
        return "{" + ", ".join(parts) + "}"
    # ── Format 2: Flat (skill manifest) ──
    parts: list[str] = []
    for prop_name, prop_def in input_schema.items():
        if not isinstance(prop_def, dict):
            parts.append(f'"{prop_name}": any')
            continue
        prop_type = prop_def.get("type", "string")
        req = " (required)" if prop_def.get("required") else " (optional)"
        parts.append(f'"{prop_name}": {prop_type}{req}')
    return "{" + ", ".join(parts) + "}"


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

        1. Run skill discovery against the goal text (Phase 3.19.3).
        2. Build a dynamic system prompt listing discovered skills and their input schemas.
        3. Call the LLM with the schema‑aware prompt.
        4. Parse the JSON plan response, extracting per‑step ``inputs``.
        5. Write PlanSegments (with per‑step inputs in context) and Plan.

        Returns the plan_id of the hydrated plan.
        Raises on LLM failure, JSON parse error, or governance rejection.
        """
        # ── 1. Skill discovery (BEFORE the LLM call — Phase 3.18.3) ──
        discovered_skills: list[S2DiscoveredSkill] = []
        if self._s3_adapter is not None:
            discovery = self._s3_adapter.discover_skills(
                S2DiscoveryQuery(query=goal, limit=10)
            )
            discovered_skills = list(discovery.skills)

        # ── 2. Build schema‑aware system prompt ──
        system_prompt = _build_system_prompt(discovered_skills if discovered_skills else None)

        # ── 3. Call the LLM ──
        raw = self._llm.chat(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
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

        # ── 4. Parse the LLM response ──
        plan_body = plan_dict["plan"]
        subgoal_text: str = plan_body["subgoal"]
        steps_list: List[Dict[str, Any]] = plan_body["steps"]
        plan_arguments: Dict[str, Any] = plan_body.get("arguments", {})

        step_descriptions = [s["description"] for s in steps_list]
        step_capabilities = [s.get("capability", "") for s in steps_list]
        step_ids = [s["id"] for s in steps_list]
        # Per-step inputs take precedence; empty steps fall back to plan-level arguments
        step_inputs = [
            s.get("inputs") or plan_arguments
            for s in steps_list
        ]

        discovered_skill_names = [sk.name for sk in discovered_skills]

        # ── 5. Write segment (with per‑step inputs in context) ──
        segment = PlanSegment(
            subgoal_id=subgoal_id,
            steps=step_descriptions,
            context={
                "capabilities": step_capabilities,
                "step_ids": step_ids,
                "step_inputs": step_inputs,
            },
            metadata={},
            skills=discovered_skill_names,
            created_at=timestamp,
        )
        governance.put_segment(segment)
        segment_ids = [segment.segment_id]

        # ── 6. Write the plan ──
        targetskillid = step_capabilities[0] if step_capabilities else (
            discovered_skill_names[0] if discovered_skill_names else "unknown"
        )
        plan = Plan(
            intent=subgoal_text,
            targetskillid=targetskillid,
            arguments=plan_arguments,
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
