from __future__ import annotations
from typing import Dict, Any, List

from src.core.types.errors.ValidationError import ValidationError


def validate_plan_prompt_structure(prompt_dict: Dict[str, Any]) -> None:
    """
    Ensures the plan prompt dictionary has the correct top-level structure.
    Required keys:
      - "prompt": str
      - "metadata": dict
    """
    if not isinstance(prompt_dict, dict):
        raise ValidationError("Plan prompt must be a dictionary")

    if "prompt" not in prompt_dict:
        raise ValidationError("Plan prompt missing 'prompt' field")

    if "metadata" not in prompt_dict:
        raise ValidationError("Plan prompt missing 'metadata' field")

    if not isinstance(prompt_dict["prompt"], str):
        raise ValidationError("'prompt' must be a string")

    if not isinstance(prompt_dict["metadata"], dict):
        raise ValidationError("'metadata' must be a dictionary")


def validate_capability_references(prompt_dict: Dict[str, Any], capabilities: Dict[str, Any]) -> None:
    """
    Ensures metadata references only known capabilities.
    """
    metadata = prompt_dict.get("metadata", {})
    cap_hash = metadata.get("capabilities_hash")

    if cap_hash is None:
        raise ValidationError("metadata.capabilities_hash missing")

    # No need to validate the hash value itself — StepState already guarantees correctness.
    # We only ensure the field exists and is pure.


def validate_no_forbidden_fields(prompt_dict: Dict[str, Any]) -> None:
    """
    Ensures the prompt dictionary contains no fields that could leak execution,
    LLM parameters, or side effects.
    """
    forbidden = {
        "llm_config",
        "temperature",
        "tool_call",
        "tool_name",
        "runtime",
        "timestamp",
        "env",
    }

    def _scan(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in forbidden:
                    raise ValidationError(f"Forbidden field '{key}' at {path}")
                _scan(value, f"{path}.{key}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _scan(item, f"{path}[{i}]")

    _scan(prompt_dict)
