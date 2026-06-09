"""
Runtime Skill dataclass (Phase 3.3.3).

Combines a validated ``SkillManifest`` with resolved ``PrimitiveBase``
objects and input/output schemas to produce a runtime‑ready skill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.capabilities.skills.manifest import SkillManifest

if TYPE_CHECKING:
    from src.capabilities.primitives.base import PrimitiveBase
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry

# ── JSON‑serializable value types (best‑effort subset) ─────────────────────
_JSON_VALUE_TYPES = (str, int, float, bool, type(None), list, dict)


def _is_json_serializable(value: Any) -> bool:
    """Best‑effort check that *value* is a JSON‑compatible type."""
    if isinstance(value, dict):
        return all(
            isinstance(k, str) and _is_json_serializable(v) for k, v in value.items()
        )
    if isinstance(value, list):
        return all(_is_json_serializable(v) for v in value)
    return isinstance(value, _JSON_VALUE_TYPES)


@dataclass
class CapabilitySkill:
    """Runtime‑ready skill combining a manifest, resolved primitives, and schemas."""

    manifest: SkillManifest
    """The validated ``SkillManifest`` this skill was built from."""

    primitives: dict[str, "PrimitiveBase"]
    """Mapping from primitive name → resolved ``PrimitiveBase`` object."""

    input_schema: dict[str, Any]
    """Validated schema describing expected inputs."""

    output_schema: dict[str, Any]
    """Validated schema describing expected outputs."""

    embedding: list[float] | None = None
    """Pre‑computed semantic embedding vector (Phase 3.19.2).

    Populated at registration time by the ``SkillEmbedder``.  Used
    only for discovery fallback when the LLM fails to name a capability.
    """

    @classmethod
    def from_manifest(
        cls,
        manifest: SkillManifest,
        registry: "PrimitiveRegistry",
    ) -> "CapabilitySkill":
        """Construct and validate a ``CapabilitySkill`` from a ``SkillManifest``.

        Args:
            manifest: A ``SkillManifest`` (must pass ``manifest.validate()``).
            registry: ``PrimitiveRegistry`` used to resolve primitive names.

        Returns:
            A fully constructed and validated ``CapabilitySkill``.

        Raises:
            ValueError: If the manifest fails validation, any primitive name
                        is unknown, or a schema is invalid.
        """
        manifest.validate()

        primitives: dict[str, PrimitiveBase] = {}
        for name in manifest.primitives:
            primitive = registry.get(name)
            if primitive is None:
                raise ValueError(f"unknown primitive: {name}")
            primitives[name] = primitive

        input_schema = manifest.inputs
        output_schema = getattr(manifest, "outputs", {}) or {}

        cls._validate_schema(input_schema, "input")
        cls._validate_schema(output_schema, "output")

        return cls(
            manifest=manifest,
            primitives=primitives,
            input_schema=input_schema,
            output_schema=output_schema,
        )

    def validate_inputs(self, data: dict[str, Any]) -> None:
        """Validate *data* against ``input_schema``.

        Raises:
            ValueError: If required keys are missing or types do not match.
        """
        _validate_against_schema(data, self.input_schema, "input")

    def validate_outputs(self, data: dict[str, Any]) -> None:
        """Validate *data* against ``output_schema``.

        Raises:
            ValueError: If required keys are missing or types do not match.
        """
        _validate_against_schema(data, self.output_schema, "output")

    def run(self, context: dict[str, Any] | None = None, **inputs: Any) -> Any:
        """Execute this skill with the given inputs.

        This is the entry point called by ``SkillRunner``.  It delegates to
        ``SkillExecutor`` and bridges the ``SkillExecutionResult`` to a
        simple return value or raised exception.

        Args:
            context: Runtime context dict passed to every primitive step
                     (e.g. ``{"search_config": SearchProviderConfig(...)}``).
            **inputs: Keyword arguments matching the skill's input schema.

        Returns:
            The ``data`` payload from the last step's ``PrimitiveResult``
            on success, or ``None`` if there are no steps.

        Raises:
            RuntimeError: If any step returns an error status.
        """
        from src.capabilities.skills.executor import SkillExecutor

        executor = SkillExecutor()
        result = executor.execute(self, inputs, context or {})
        if result.status == "error":
            raise RuntimeError(result.error or "skill execution failed")
        if result.results:
            return result.results[-1].data
        return None

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_schema(schema: dict[str, Any], label: str) -> None:
        """Validate that *schema* is a well‑formed JSON‑Schema‑like dict."""
        if not isinstance(schema, dict):
            raise ValueError(f"{label}_schema must be a dict")
        if not all(isinstance(k, str) for k in schema):
            raise ValueError(f"{label}_schema keys must be strings")
        if not _is_json_serializable(schema):
            raise ValueError(f"{label}_schema values must be JSON-serializable")


# ── schema‑based data validation ──────────────────────────────────────────

_SCHEMA_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def _validate_against_schema(
    data: dict[str, Any], schema: dict[str, Any], label: str
) -> None:
    """Validate *data* against a JSON‑Schema‑like *schema* dict.

    Supports ``type``, ``properties``, and ``required``.
    """
    if not isinstance(data, dict):
        raise ValueError(f"{label} data must be a dict, got {type(data).__name__}")

    schema_type = schema.get("type")
    if schema_type and schema_type != "object":
        raise ValueError(f"{label}_schema type must be 'object', got {schema_type!r}")

    properties = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    # Check required keys.
    for key in required:
        if key not in data:
            raise ValueError(f"{label} missing required key: {key!r}")

    # Check types for supplied keys that have a schema property.
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
            raise ValueError(
                f"{label}.{key} expected {expected_type}, got {type(value).__name__}"
            )
