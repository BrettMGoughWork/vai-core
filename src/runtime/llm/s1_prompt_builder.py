"""
Phase 2.14.4 — S1 Prompt Builder
=================================

Builds strict JSON-only prompts for the S1 LLM backend.
Pure function. No I/O. No inference.

The prompt builder wraps a PromptRequest into a fully structured
payload that instructs the LLM to respond ONLY with valid JSON.
No free-form text is permitted in the prompt or the response.

The output is a dict representing the complete prompt payload:
- system_instruction: strict JSON-only rules
- schema: the expected JSON response schema
- context: the request's plan_context, memory, and tool_context
- examples: valid and invalid JSON response examples
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from src.domain.interfaces.contract import PromptRequest


# ──────────────────────────────────────────────────────────────────────────────
# JSON response schema (the contract the LLM must follow)
# ──────────────────────────────────────────────────────────────────────────────

RESPONSE_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": [
        "drift_detected",
        "drift_type",
        "drift_severity",
        "drift_detail",
        "repairs",
        "quality",
        "structural_deviation",
        "progress",
        "is_complete",
        "confidence",
        "next_action",
        "blockers",
        "shaped",
        "steps",
        "segments",
    ],
    "properties": {
        "drift_detected": {
            "type": "boolean",
            "description": "True if the current subgoal/segment has drifted from the plan.",
        },
        "drift_type": {
            "type": ["string", "null"],
            "description": "The category of drift, or null if none. One of: structural, behavioural, quality_below_threshold, missing_prompt, missing_memory, missing_plan_context, missing_subgoal_context, missing_segment_context, missing_subgoal_index, missing_subgoal_state, missing_segment_index, missing_segment_state, missing_instruction, invalid_state, non_integer_index.",
        },
        "drift_severity": {
            "type": "string",
            "enum": ["minor", "major", "catastrophic"],
            "description": "Severity of the drift.",
        },
        "drift_detail": {
            "type": "array",
            "items": {"type": "object"},
            "description": "Detailed drift signal entries. Empty array if no drift.",
        },
        "repairs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["target", "action"],
                "properties": {
                    "target": {"type": "string"},
                    "action": {"type": "string", "enum": ["fill_default", "normalize", "remove", "replace"]},
                    "replacement": {},
                },
            },
            "description": "Repair proposals. Empty array if no repairs needed.",
        },
        "quality": {
            "type": "object",
            "required": ["below_threshold"],
            "properties": {
                "below_threshold": {"type": "boolean"},
            },
        },
        "structural_deviation": {
            "type": "object",
            "description": "Description of any structural deviation from the expected shape.",
        },
        "progress": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Progress through the current segment (0.0 to 1.0).",
        },
        "is_complete": {
            "type": "boolean",
            "description": "True if the current segment has reached completion.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence in the response quality.",
        },
        "next_action": {
            "type": "string",
            "description": "The recommended next action: continue, retry, repair, advance_segment, escalate, execute_segment, continue_execution, repair_and_retry, abort.",
        },
        "blockers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of blocking issues (empty if none).",
        },
        "shaped": {
            "type": "boolean",
            "description": "True if the plan was shaped (always true in output).",
        },
        "steps": {
            "type": "array",
            "items": {"type": "object"},
            "description": "Shaped steps (empty in simulation).",
        },
        "segments": {
            "type": "array",
            "items": {"type": "object"},
            "description": "Shaped segments (empty in simulation).",
        },
    },
    "additionalProperties": False,
}


# ──────────────────────────────────────────────────────────────────────────────
# System instruction — the strict rules the LLM must follow
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_INSTRUCTION: str = (
    "You are a deterministic reasoning assistant for an agent runtime. "
    "You receive structured context about the current execution state "
    "(subgoal, segment, memory) and you MUST respond ONLY with a JSON object "
    "conforming to the schema below.\n\n"
    "RULES:\n"
    "1. Respond ONLY with valid JSON. No text before or after the JSON.\n"
    "2. Do NOT include explanations, commentary, or natural language.\n"
    "3. Do NOT include markdown fences (```json). Output raw JSON only.\n"
    "4. Every field in the schema is REQUIRED.\n"
    "5. Do NOT add extra fields beyond those in the schema.\n"
    "6. Use the provided examples as templates for valid/invalid responses.\n"
    "7. If the context is complete and valid, set drift_detected=false and dr"
    "ift_type=null.\n"
    "8. If you detect structural or behavioural issues, populate drift_detail"
    " and repairs accordingly."
)


# ──────────────────────────────────────────────────────────────────────────────
# Valid response examples
# ──────────────────────────────────────────────────────────────────────────────

VALID_EXAMPLE_NO_DRIFT: Dict[str, Any] = {
    "drift_detected": False,
    "drift_type": None,
    "drift_severity": "minor",
    "drift_detail": [],
    "repairs": [],
    "quality": {"below_threshold": False},
    "structural_deviation": {},
    "progress": 0.5,
    "is_complete": False,
    "confidence": 0.95,
    "next_action": "continue_execution",
    "blockers": [],
    "shaped": True,
    "steps": [],
    "segments": [],
}

VALID_EXAMPLE_WITH_DRIFT: Dict[str, Any] = {
    "drift_detected": True,
    "drift_type": "missing_instruction",
    "drift_severity": "minor",
    "drift_detail": [
        {
            "drift_detected": True,
            "drift_type": "missing_instruction",
            "drift_severity": "minor",
            "drift_detail": {"field": "prompt.instruction", "reason": "missing"},
        }
    ],
    "repairs": [
        {
            "target": "prompt.instruction",
            "action": "fill_default",
            "replacement": "Execute the current subgoal and segment.",
        }
    ],
    "quality": {"below_threshold": True},
    "structural_deviation": {"field": "prompt.instruction", "reason": "missing"},
    "progress": 0.0,
    "is_complete": False,
    "confidence": 0.85,
    "next_action": "repair_and_retry",
    "blockers": [],
    "shaped": True,
    "steps": [],
    "segments": [],
}


# ──────────────────────────────────────────────────────────────────────────────
# Invalid response examples (what NOT to do)
# ──────────────────────────────────────────────────────────────────────────────

INVALID_EXAMPLE_FREE_FORM: Dict[str, Any] = {
    "explanation": "This is wrong because it includes natural language",
    "drift": {"detected": False},
}

INVALID_EXAMPLE_EXTRA_FIELDS: Dict[str, Any] = {
    "drift_detected": False,
    "drift_type": None,
    "drift_severity": "minor",
    "drift_detail": [],
    "repairs": [],
    "quality": {"below_threshold": False},
    "structural_deviation": {},
    "progress": 0.5,
    "is_complete": False,
    "confidence": 0.95,
    "next_action": "continue_execution",
    "blockers": [],
    "shaped": True,
    "steps": [],
    "segments": [],
    "extra_narrative_field": "This field is not in the schema and must not be included.",
}

INVALID_EXAMPLE_MISSING_FIELDS: Dict[str, Any] = {
    "drift_detected": False,
    "drift_type": None,
}


# ──────────────────────────────────────────────────────────────────────────────
# Main builder function
# ──────────────────────────────────────────────────────────────────────────────


def build_llm_prompt(request: PromptRequest) -> Dict[str, Any]:
    """Build a strict JSON-only prompt for the LLM.

    Pure function. No I/O. No inference.

    The returned dict contains:
        - system_instruction: the strict rules for the LLM
        - response_schema: the complete JSON schema for the expected response
        - context: the plan_context, memory, and tool_context from the request
        - valid_examples: list of valid response examples
        - invalid_examples: list of invalid response examples (with explanations)

    Args:
        request: A PromptRequest from S2.

    Returns:
        A fully structured, JSON-safe dict representing the LLM prompt.
        No free-form text is included.
    """
    # Build the context from the request — shallow copy to avoid mutation
    context = {
        "plan_context": deepcopy(request.plan_context),
        "memory": deepcopy(request.memory),
        "tool_context": deepcopy(request.tool_context),
    }

    # If the request has a custom prompt instruction, include it in context
    if isinstance(request.prompt, dict) and "instruction" in request.prompt:
        context["instruction"] = request.prompt["instruction"]

    return {
        "system_instruction": SYSTEM_INSTRUCTION,
        "response_schema": RESPONSE_SCHEMA,
        "context": context,
        "valid_examples": [
            {
                "label": "No-drift response (clean execution)",
                "response": VALID_EXAMPLE_NO_DRIFT,
            },
            {
                "label": "With-drift response (structural issue detected)",
                "response": VALID_EXAMPLE_WITH_DRIFT,
            },
        ],
        "invalid_examples": [
            {
                "label": "Free-form text response (NOT allowed)",
                "response": INVALID_EXAMPLE_FREE_FORM,
                "why_invalid": "Contains natural language explanation. Must be pure JSON with all required fields.",
            },
            {
                "label": "Extra fields (NOT allowed)",
                "response": INVALID_EXAMPLE_EXTRA_FIELDS,
                "why_invalid": "Contains 'extra_narrative_field' which is not in the schema. No additional properties are permitted.",
            },
            {
                "label": "Missing required fields (NOT allowed)",
                "response": INVALID_EXAMPLE_MISSING_FIELDS,
                "why_invalid": "Missing required fields: drift_severity, drift_detail, repairs, quality, structural_deviation, progress, is_complete, confidence, next_action, blockers, shaped, steps, segments.",
            },
        ],
    }
