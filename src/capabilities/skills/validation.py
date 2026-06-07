"""
Skill validation (Phase 3.3.5).

Provides parse-time and execution-time validation functions for Skills:
- ``validate_manifest_structure`` — parse-time checks (registry, schema, steps)
- ``validate_execution_args`` — execution-time input validation
- ``validate_step_result`` — execution-time output validation per step
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.capabilities.primitives.types import PrimitiveResult

if TYPE_CHECKING:
    from src.capabilities.skills.manifest import SkillManifest
    from src.capabilities.skills.skill import CapabilitySkill

_SCHEMA_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def _is_json_serializable(value: Any) -> bool:
    """Best-effort check that *value* is a JSON-compatible type."""
    if isinstance(value, dict):
        return all(
            isinstance(k, str) and _is_json_serializable(v) for k, v in value.items()
        )
    if isinstance(value, list):
        return all(_is_json_serializable(v) for v in value)
    return isinstance(value, (str, int, float, bool, type(None), list, dict))


def validate_manifest_structure(manifest: SkillManifest, registry: Any) -> None:
    """Parse-time validation of a ``SkillManifest`` against a registry.

    Checks:
      - Every primitive name in *manifest.primitives* exists in *registry*.
      - *manifest.inputs* is a well-formed schema dict.
      - Every step has valid ``call`` / ``args`` / ``on_error`` fields.

    Raises:
        ValueError: On any validation failure.
    """
    # A. Primitive existence
    for name in manifest.primitives:
        if registry.get(name) is None:
            raise ValueError(f"unknown primitive: {name}")

    # B. Input schema validation
    if not isinstance(manifest.inputs, dict):
        raise ValueError("invalid input schema")
    if not all(isinstance(k, str) for k in manifest.inputs):
        raise ValueError("invalid input schema")
    if not _is_json_serializable(manifest.inputs):
        raise ValueError("invalid input schema")

    # C. Step ordering validation
    for i, step in enumerate(manifest.steps):
        if not isinstance(step, dict):
            raise ValueError("invalid step structure")

        if "call" not in step or "args" not in step:
            raise ValueError("invalid step structure")

        call = step["call"]
        if call not in manifest.primitives:
            raise ValueError("invalid step structure")

        if not isinstance(step["args"], dict):
            raise ValueError("invalid step structure")

        on_error = step.get("on_error")
        if on_error is not None and not isinstance(on_error, str):
            raise ValueError("invalid step structure")


def validate_execution_args(skill: CapabilitySkill, args: dict[str, Any]) -> None:
    """Execution-time validation of *args* against *skill.input_schema*.

    Checks:
      - *args* is a dict.
      - All required keys in the input schema are present.
      - Types match schema expectations (simple ``isinstance`` checks).

    Raises:
        ValueError: On mismatch.
    """
    if not isinstance(args, dict):
        raise ValueError("invalid execution args")

    schema = skill.input_schema
    required: list[str] = schema.get("required", [])

    for key in required:
        if key not in args:
            raise ValueError("invalid execution args")

    properties = schema.get("properties", {})
    for key, value in args.items():
        prop = properties.get(key)
        if prop is None:
            continue
        expected_type = prop.get("type")
        if expected_type is None:
            continue
        expected = _SCHEMA_TYPE_MAP.get(expected_type)
        if expected is None:
            continue
        if not isinstance(value, expected):
            raise ValueError("invalid execution args")


def validate_step_result(
    skill: CapabilitySkill,
    step_result: PrimitiveResult,
    step_index: int,
) -> None:
    """Execution-time validation of a step's ``PrimitiveResult``.

    - If *step_result.status* is ``"error"``, returns immediately (the
      executor handles it).
    - If this is the final step and *step_result.data* exists, validates
      it against *skill.output_schema*.

    Raises:
        ValueError: On schema mismatch.
    """
    if step_result.status == "error":
        return

    total_steps = len(skill.manifest.steps)
    if step_index != total_steps - 1 or step_result.data is None:
        return

    data = step_result.data
    if not isinstance(data, dict):
        raise ValueError("invalid step output")

    schema = skill.output_schema
    required: list[str] = schema.get("required", [])

    for key in required:
        if key not in data:
            raise ValueError("invalid step output")

    properties = schema.get("properties", {})
    for key, value in data.items():
        prop = properties.get(key)
        if prop is None:
            continue
        expected_type = prop.get("type")
        if expected_type is None:
            continue
        expected = _SCHEMA_TYPE_MAP.get(expected_type)
        if expected is None:
            continue
        if not isinstance(value, expected):
            raise ValueError("invalid step output")
