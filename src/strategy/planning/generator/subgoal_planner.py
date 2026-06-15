"""
SubgoalPlanner — generates a Plan and PlanSegments for a subgoal via an injected
``llm_complete`` callback.

Used by agent_planner.AgentPlanner when an active subgoal has no plan in PlanMemory.
All hydration and decomposition use existing types and memory substrates; no new abstractions.

The ``llm_complete`` callback receives (system_prompt, user_message) and must return
the JSON content string (plain str, not wrapped in the OpenAI response envelope).

To switch to a live LLM, wrap any ChatProvider in an ``llm_complete`` callable::

    def _complete(sys: str, usr: str) -> str:
        raw = provider.chat(model="gpt-4", messages=[
            {"role": "system", "content": sys},
            {"role": "user", "content": usr},
        ])
        return raw["choices"][0]["message"]["content"]

    SubgoalPlanner(llm_complete=_complete)
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Dict, List

from src.strategy.memory.governance.memory_governance import MemoryGovernance
from src.strategy.planning.models.plan import Plan
from src.strategy.planning.segments.manager import PlanSegmentManager
from src.strategy.types.hashing import stable_hash
from src.strategy.types.plan_segment import PlanSegment


def _build_system_prompt(skill_refs: list[str] | None = None) -> str:
    """Build a dynamic system prompt, optionally listing available skill names.

    When *skill_refs* are provided, each skill name is injected so the LLM can
    reference real capability names in its plan steps.
    """
    skill_block = ""
    if skill_refs:
        lines: list[str] = ["AVAILABLE CAPABILITIES:"]
        for name in skill_refs:
            lines.append(f"- {name}")
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
        '- MULTI-STEP: When the user\'s goal contains sequencing words like "then", "and then", "after that", or "finally", you MUST split the work into one step per clause. Do NOT combine multiple sequential actions into a single step.\n'
        "- CROSS-STEP REFERENCES: When a step needs output from a previous step, you MUST reference the EXACT output key name using the \"{{key}}\" template format. Look at the Outputs field of the prior step's capability to find valid key names. For example, if step 1 uses \"stdlib.text.split\" whose Outputs are {\"parts\": \"list\", \"count\": \"number\"} and step 2 needs the split parts, write {{\"chunks\": \"{{parts}}\"}}. If step 2 needs both parts and count: {{\"chunks\": \"{{parts}}\", \"total\": \"{{count}}\"}}. NEVER invent key names — only use keys explicitly listed in the capability's Outputs.\n"
        '- NEVER use "$.steps[N]" JSONPath expressions to reference prior-step outputs.\n'
        '- NEVER use {"$ref": "..."} objects to reference prior-step outputs.\n'
        '- NEVER use "{{step-1}}", "{{step-2}}", or any {{step-N}} pattern to reference prior-step outputs. Always reference the SPECIFIC output key name (e.g., "{{value}}", "{{text}}", "{{result}}").\n'
        '- Use descriptive step IDs (e.g., "fetch-data", "parse-html") rather than generic IDs like "step-1".\n'
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
        llm_complete: Callable[[str, str], str] | None = None,
        segment_manager: PlanSegmentManager | None = None,
    ) -> None:
        self._llm_complete = llm_complete
        self._segment_manager = segment_manager

    def plan_for_subgoal(
        self,
        subgoal_id: str,
        goal: str,
        governance: MemoryGovernance,
        timestamp: str,
        skill_refs: list[str] | None = None,
    ) -> str:
        """
        Generate and hydrate a plan for the given subgoal.

        1. Build a system prompt listing available skill names (if provided).
        2. Call the LLM with the prompt.
        3. Parse the JSON plan response, extracting per‑step ``inputs``.
        4. Write PlanSegments (with per‑step inputs in context) and Plan.

        Args:
            subgoal_id: ID of the subgoal to plan for.
            goal: The goal text to plan against.
            governance: MemoryGovernance for persisting plan artifacts.
            timestamp: ISO timestamp for deterministic IDs.
            skill_refs: Symbolic skill names pre-resolved by S5 (no S3 coupling).

        Returns the plan_id of the hydrated plan.
        Raises on LLM failure, JSON parse error, or governance rejection.
        """
        # ── 1. Build system prompt with available skill names ──
        system_prompt = _build_system_prompt(skill_refs)

        # ── 3. Call the LLM via injected callback ──
        if self._llm_complete is None:
            raise RuntimeError("SubgoalPlanner has no llm_complete callback configured")
        content: str = self._llm_complete(system_prompt, goal)
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

        # ── 5. Write segment (with per‑step inputs in context) ──
        segment_context = {
            "capabilities": step_capabilities,
            "step_ids": step_ids,
            "step_inputs": step_inputs,
        }
        if self._segment_manager is not None:
            segment = self._segment_manager.create_segment(
                subgoal_id=subgoal_id,
                steps=step_descriptions,
                context=segment_context,
                metadata={},
                skills=skill_refs or [],
                created_at=timestamp,
            )
        else:
            segment = PlanSegment(
                subgoal_id=subgoal_id,
                steps=step_descriptions,
                context=segment_context,
                metadata={},
                skills=skill_refs or [],
                created_at=timestamp,
            )
        governance.put_segment(segment)
        segment_ids = [segment.segment_id]

        # ── 6. Write the plan ──
        targetskillid = step_capabilities[0] if step_capabilities else (
            skill_refs[0] if skill_refs else "unknown"
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
