"""LLMDecomposer — decomposer that uses an LLM for task decomposition.

Calls the StrategyRouter to ask the LLM to split a non-atomic task into
a DAG of subtasks.  Parses structured JSON from the LLM response and
validates the DAG before returning the ``DecompositionPlan``.

The prompt instructs the LLM to choose a merge strategy and produce
subtasks with clear dependency relationships.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from src.agent.decomposition.dag_validator import (
    DagValidationError,
    validate_dag,
)
from src.agent.strategy_router import RouterOutcome, StrategyRouter
from src.agent.types.decomposition import (
    DecompositionPlan,
    DecompositionRequest,
    SubtaskSpec,
)

logger = logging.getLogger(__name__)

_DECOMPOSITION_SYSTEM_PROMPT = """\
You are a task decomposition planner. Your job is to break down a complex
task into smaller, atomic subtasks that can be executed in parallel where
possible.

Rules:
1. Each subtask must be atomic — it should do ONE thing.
2. Use ``depends_on`` to express ordering constraints (list of subtask IDs
   that must complete before this one can start).
3. Independent subtasks (empty ``depends_on``) will run in parallel.
4. Keep the total number of subtasks reasonable (2-8 recommended).
5. Choose a merge strategy from: "concat" (concatenate results in order),
   "summarize_llm" (synthesize with an LLM), "select_best" (pick the best).
6. Each subtask can target a specific agent (use ``agent_tool`` pattern
   like "research" or "code") or be a general subtask (leave target null).

Respond with valid JSON only, in this exact format:
{
  "subtasks": [
    {
      "id": "subtask-1",
      "description": "What this subtask does",
      "target_agent_id": null,
      "depends_on": [],
      "priority": 0,
      "timeout_seconds": 300
    }
  ],
  "merge_strategy": "concat",
  "reasoning": "Brief explanation of the decomposition"
}
```"""


class DecompositionParseError(Exception):
    """Raised when the LLM response cannot be parsed as a DecompositionPlan."""


class LLMDecomposer:
    """Decomposer that delegates task decomposition to an LLM.

    Args:
        strategy_router: The StrategyRouter used to call the LLM.
    """

    def __init__(self, strategy_router: StrategyRouter) -> None:
        self._strategy_router = strategy_router

    def decompose(
        self,
        request: DecompositionRequest,
    ) -> DecompositionPlan | None:
        """Decompose *request* via LLM call.

        Returns:
            A validated ``DecompositionPlan``, or ``None`` if the task
            cannot be meaningfully decomposed (the LLM indicates the
            task is atomic or the response is unparseable).
        """
        # ── Build the prompt ──────────────────────────────────────────
        agent_context = ""
        if request.available_agents:
            agent_context = (
                "Available agents:\n"
                + "\n".join(f"  - {a}" for a in request.available_agents)
            )

        constraints = request.constraints
        max_children = constraints.get("max_children", 8)
        max_depth = constraints.get("max_depth", 2)

        user_message = (
            f"Decompose the following task into at most {max_children} "
            f"subtasks (max depth {max_depth}):\n\n"
            f"TASK: {request.parent_task}\n\n"
            f"{agent_context}\n\n"
            "Respond with valid JSON only."
        )

        prompt = {
            "message": user_message,
            "agent_id": "_decomposer_",
            "agent_metadata": {
                "name": "Task Decomposer",
                "description": "Breaks complex tasks into parallel subtasks.",
            },
        }

        outcome = RouterOutcome(
            type="llm_call",
            payload={
                "prompt": prompt,
                "backend": "conversational",
                "memory": {"conversation_history": []},
                "plan_context": {},
                "tool_context": [],
            },
        )

        # ── Call the LLM ──────────────────────────────────────────────
        result = self._strategy_router.route(outcome)

        if result.get("error"):
            logger.warning(
                "LLM decomposition failed: %s", result["error"],
            )
            return None

        raw_output = result.get("output", {})

        # The LLM may return either a dict with "message" or a plain string
        if isinstance(raw_output, dict):
            raw_text = raw_output.get("message", json.dumps(raw_output))
        else:
            raw_text = str(raw_output)

        # ── Parse the JSON ────────────────────────────────────────────
        try:
            parsed = self._parse_llm_output(raw_text)
        except DecompositionParseError as exc:
            logger.warning("Failed to parse LLM decomposition: %s", exc)
            return None

        if not parsed.get("subtasks"):
            # LLM says the task is atomic
            return None

        # ── Build SubtaskSpecs ─────────────────────────────────────────
        plan_id = f"decomp-{uuid.uuid4().hex[:12]}"
        subtasks = self._build_subtasks(parsed["subtasks"], request)

        # ── Validate DAG ──────────────────────────────────────────────
        try:
            validate_dag(subtasks)
        except DagValidationError as exc:
            logger.warning(
                "LLM produced invalid DAG (plan=%s): %s", plan_id, exc,
            )
            return None

        merge_strategy = parsed.get("merge_strategy", "concat")
        if merge_strategy not in ("concat", "summarize_llm", "select_best"):
            merge_strategy = "concat"

        return DecompositionPlan(
            plan_id=plan_id,
            parent_task=request.parent_task,
            subtasks=subtasks,
            merge_strategy=merge_strategy,
            metadata={
                "reasoning": parsed.get("reasoning", ""),
                "source": "llm_decomposer",
            },
        )

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _parse_llm_output(raw_text: str) -> dict[str, Any]:
        """Extract JSON from LLM output.

        Handles common wrapping (```json blocks, trailing text).
        """
        text = raw_text.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            # Find the first { or [ after the opening fence
            start = text.find("{")
            if start == -1:
                start = text.find("[")
            if start == -1:
                raise DecompositionParseError(
                    "No JSON object found in LLM output"
                )
            text = text[start:]

        # Remove trailing ``` if present
        if text.endswith("```"):
            text = text[:-3].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise DecompositionParseError(
                f"Invalid JSON from LLM: {exc}"
            ) from exc

    @staticmethod
    def _build_subtasks(
        raw_subtasks: list[dict[str, Any]],
        request: DecompositionRequest,
    ) -> list[SubtaskSpec]:
        """Convert raw dict subtasks from the LLM into ``SubtaskSpec``."""
        subtasks: list[SubtaskSpec] = []
        for i, entry in enumerate(raw_subtasks):
            sid: str = entry.get("id", f"subtask-{i + 1}")
            description: str = entry.get("description", "")
            if not description:
                description = f"Subtask {sid}"

            target_agent = entry.get("target_agent_id")
            # Validate that the target agent is in the available list
            if (
                target_agent
                and request.available_agents
                and target_agent not in request.available_agents
            ):
                logger.info(
                    "LLM requested unavailable agent %r — clearing target",
                    target_agent,
                )
                target_agent = None

            subtasks.append(
                SubtaskSpec(
                    id=sid,
                    description=description,
                    target_agent_id=target_agent,
                    target_skill_id=entry.get("target_skill_id"),
                    arguments=entry.get("arguments", {}),
                    depends_on=entry.get("depends_on", []),
                    priority=entry.get("priority", 0),
                    timeout_seconds=entry.get("timeout_seconds", 300),
                    max_retries=entry.get("max_retries", 2),
                )
            )
        return subtasks
