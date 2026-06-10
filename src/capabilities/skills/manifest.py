"""
Skill manifest dataclass (Phase 3.3.2).

Defines a structured, validated representation of a parsed .skill.md
manifest — metadata, primitive references, input schema, and ordered
execution steps.  File parsing is handled separately by skill_parser.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillManifest:
    """Validated representation of a .skill.md manifest."""

    name: str
    """Skill name."""

    description: str
    """Human-readable description of what this skill does."""

    primitives: list[str] = field(default_factory=list)
    """List of primitive names this skill depends on."""

    inputs: dict[str, Any] = field(default_factory=dict)
    """Schema describing expected inputs."""

    steps: list[dict[str, Any]] = field(default_factory=list)
    """Ordered list of execution steps."""

    def validate(self) -> None:
        """Validate all fields, step structure, and primitive references.

        Raises:
            ValueError: If any field is missing, has the wrong type, or if any
                        step references a primitive not listed in *primitives*.
        """
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("SkillManifest.name must be a non-empty str")
        if not isinstance(self.description, str) or not self.description:
            raise ValueError("SkillManifest.description must be a non-empty str")
        if not isinstance(self.primitives, list):
            raise ValueError("SkillManifest.primitives must be a list")
        if not all(isinstance(p, str) for p in self.primitives):
            raise ValueError("SkillManifest.primitives must be a list of str")
        if not isinstance(self.inputs, dict):
            raise ValueError("SkillManifest.inputs must be a dict")
        if not isinstance(self.steps, list):
            raise ValueError("SkillManifest.steps must be a list")

        primitive_set = set(self.primitives)
        for i, step in enumerate(self.steps):
            if not isinstance(step, dict):
                raise ValueError(
                    f"SkillManifest.steps[{i}] must be a dict, got {type(step).__name__}"
                )

            # ── return step ── (terminal step: return a value or template)
            if "return" in step:
                # A return step is valid as-is; nothing else to validate.
                continue

            # ── call step ── (invoke a primitive)
            call = step.get("call")
            if not isinstance(call, str):
                raise ValueError(
                    f"SkillManifest.steps[{i}].call must be a str, "
                    f"got {type(call).__name__}"
                )

            if call not in primitive_set:
                raise ValueError(
                    f"SkillManifest.steps[{i}].call='{call}' is not listed "
                    f"in SkillManifest.primitives"
                )

            args = step.get("args")
            if args is not None and not isinstance(args, dict):
                raise ValueError(
                    f"SkillManifest.steps[{i}].args must be a dict, got {type(args).__name__}"
                )

            on_error = step.get("on_error")
            if on_error is not None and not isinstance(on_error, str):
                raise ValueError(
                    f"SkillManifest.steps[{i}].on_error must be str or None, "
                    f"got {type(on_error).__name__}"
                )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillManifest:
        """Construct and validate a SkillManifest from a dictionary.

        Args:
            data: Dict produced by the .skill.md parser.

        Returns:
            A validated ``SkillManifest`` instance.

        Raises:
            ValueError: If *data* fails validation.
        """
        manifest = cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            primitives=data.get("primitives", []),
            inputs=data.get("inputs", {}),
            steps=data.get("steps", []),
        )
        manifest.validate()
        return manifest
