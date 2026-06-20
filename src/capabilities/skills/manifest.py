"""
Skill manifest dataclass (Phase 3.3.2 / 3.15.2).

Defines a structured, validated representation of a parsed .skill.md
manifest — metadata, primitive references, input schema, and ordered
execution steps.  File parsing is handled separately by skill_parser.py.

PHASE 3.15.2: Added ``plugin_name``, ``plugin_version``, and
``manifest_hash`` for stable embedding IDs and registry snapshots.
"""

from __future__ import annotations

import hashlib
import json

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

    plugin_name: str | None = None
    """Owning plugin name, or ``None`` for stdlib skills (3.15)."""

    plugin_version: str | None = None
    """Owning plugin version, or ``None`` for stdlib skills (3.15)."""

    manifest_hash: str | None = None
    """SHA-256 of canonical skill definition (3.15.2 — stable embedding IDs)."""

    execution_contract: dict[str, Any] | None = None
    """Optional execution semantics contract declaration (3.21.2).

    When present, parsed into a ``SkillExecutionContract`` by
    ``CapabilitySkill.from_manifest()``.  Raw dict form keeps the
    manifest JSON-pure.
    """

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
                continue

            # ── switch step ── (conditional branch based on input values)
            if "switch" in step:
                _validate_switch_step(step, i, primitive_set)
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
            plugin_name=data.get("plugin_name"),
            plugin_version=data.get("plugin_version"),
            execution_contract=data.get("execution_contract"),
        )
        manifest.manifest_hash = _compute_manifest_hash(manifest)
        manifest.validate()
        return manifest


def _compute_manifest_hash(manifest: SkillManifest) -> str:
    """Compute a stable SHA-256 hash of the skill's canonical definition."""
    canonical: dict[str, Any] = {
        "name": manifest.name,
        "description": manifest.description,
        "primitives": sorted(manifest.primitives),
        "steps": manifest.steps,
    }
    json_bytes = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(json_bytes).hexdigest()


def _validate_switch_step(step: dict, idx: int, primitive_set: set[str]) -> None:
    """Validate a ``switch`` step structure."""
    branches = step["switch"]
    if not isinstance(branches, list):
        raise ValueError(
            f"SkillManifest.steps[{idx}].switch must be a list, "
            f"got {type(branches).__name__}"
        )
    seen_default = False
    for j, branch in enumerate(branches):
        if not isinstance(branch, dict):
            raise ValueError(
                f"SkillManifest.steps[{idx}].switch[{j}] must be a dict, "
                f"got {type(branch).__name__}"
            )
        if "default" in branch:
            if seen_default:
                raise ValueError(
                    f"SkillManifest.steps[{idx}].switch has multiple default branches"
                )
            seen_default = True
            # YAML: default: is a key with null value; steps are at the same level.
            inner = branch.get("steps", [])
        elif "case" in branch:
            inner = branch.get("steps", [])
        else:
            raise ValueError(
                f"SkillManifest.steps[{idx}].switch[{j}] must have 'case' or 'default'"
            )
        if not isinstance(inner, list):
            raise ValueError(
                f"SkillManifest.steps[{idx}].switch[{j}] steps must be a list"
            )
        for k, sub in enumerate(inner):
            if not isinstance(sub, dict):
                raise ValueError(
                    f"SkillManifest.steps[{idx}].switch[{j}].steps[{k}] "
                    f"must be a dict"
                )
            if "call" in sub:
                call = sub.get("call")
                if not isinstance(call, str):
                    raise ValueError(
                        f"SkillManifest.steps[{idx}].switch[{j}].steps[{k}].call "
                        f"must be a str, got {type(call).__name__}"
                    )
                if call not in primitive_set:
                    raise ValueError(
                        f"SkillManifest.steps[{idx}].switch[{j}].steps[{k}].call="
                        f"'{call}' is not listed in SkillManifest.primitives"
                    )
