from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any

from src.core.planning.validators.cognitive_normaliser import normalise_cognitive_structure
from src.core.planning.safety.purity_enforcer import enforce_cognitive_purity
from src.core.planning.models.step_state import StepState

from src.core.planning.validators.plan_validators import (
    validate_plan_prompt_structure,
    validate_capability_references,
    validate_no_forbidden_fields,
)

@dataclass(frozen=True)
class PlanPrompt:
    """Pure, deterministic prompt template for Stratum‑1 execution."""
    prompt: str
    metadata: Dict[str, Any]


class PlanGenerator:
    """
    Deterministic Stratum‑2 component that produces a canonical
    plan‑generation prompt template. No LLM calls occur here.
    """

    def __init__(self, capabilities: Dict[str, Any]):
        self.capabilities = capabilities

    def generate(self, state: StepState) -> PlanPrompt:
        raw_prompt = self._build_prompt_dict(state)

        # Structural validation
        validate_plan_prompt_structure(raw_prompt)
        validate_capability_references(raw_prompt, self.capabilities)
        validate_no_forbidden_fields(raw_prompt)

        # Canonical normalisation
        normalised = normalise_cognitive_structure(raw_prompt)

        # Purity enforcement
        enforce_cognitive_purity(normalised)

        return PlanPrompt(
            prompt=normalised["prompt"],
            metadata=normalised["metadata"],
        )

    def _build_prompt_dict(self, state: StepState) -> Dict[str, Any]:
        """
        Deterministic construction of the prompt dictionary.
        No side effects, no randomness, no LLM calls.
        """
        return {
            "prompt": self._render_prompt(state),
            "metadata": {
                "capabilities_hash": state.capabilities_hash,
                "state_hash": state.state_hash,
                "version": "2.2.1",
            },
        }

    def _render_prompt(self, state: StepState) -> str:
        """
        Render the actual prompt template string.
        This is deterministic and contains no model parameters.
        """
        # Placeholder — filled in during 2.2.1 prompt‑design step
        return (
            """You are the Plan Generator for a deterministic agent runtime.

Your task is to produce a plan in strict JSON format that satisfies the following rules:

1. The plan must be a JSON object with a top-level "steps" array.
2. Each step must be a JSON object with:
   - "id": a unique string identifier
   - "action": the name of a capability from the provided capabilities list
   - "input": a JSON object containing only the fields required by that capability
3. You must not invent capabilities. You may only use capabilities explicitly listed in the "capabilities" section.
4. You must not invent fields inside "input". You may only use fields defined by the capability schema.
5. If the user request cannot be satisfied with the available capabilities, return:
   {"error": "NO_VALID_PLAN"}
6. The plan must be minimal, deterministic, and contain no commentary, no explanations, and no natural language outside JSON.
7. The plan must not contain timestamps, randomness, or any non-deterministic values.
8. The plan must not contain tool calls, LLM calls, or any execution instructions.

You will be given:
- "user_request": the user's original request
- "state": the current cognitive state (read-only)
- "capabilities": the list of available capabilities and their schemas

Your output must be ONLY valid JSON matching the plan schema.

Begin."""
        )
