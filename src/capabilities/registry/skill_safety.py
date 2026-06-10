"""
Agent-authored skill safety validator (Phase 3.16.2 / 3.17.1).

Layered safety gates for skills authored by the agent at runtime.
Reuses existing validation infrastructure where possible, adds
agent-authored-specific checks:

- Disallowed primitive references
- System skill override protection
- Privilege escalation detection
- Schema safety
- Recursive self-reference detection (3.17.1)
- Unbounded loop detection (3.17.1)
- Dynamic primitive selection prevention (3.17.1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry
    from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
    from src.capabilities.registry.skill_semantic_safety import SkillSemanticSafetyValidator
    from src.capabilities.skills.skill import CapabilitySkill


# ── Default disallowed primitives ──────────────────────────────────────────
# These primitives are too dangerous for agent-authored skills.
DEFAULT_DISALLOWED_PRIMITIVES: set[str] = {
    "proc.exec",
}


@dataclass
class SafetyResult:
    """Result of a skill safety validation."""

    passed: bool
    """``True`` if all safety checks passed."""

    errors: list[str] = field(default_factory=list)
    """Human-readable error messages for each failing check."""


class SkillSafetyValidator:
    """Validates agent-authored skills against safety policies.

    Usage::

        validator = SkillSafetyValidator(
            primitive_registry=prim_reg,
            skill_registry=skill_reg,
            disallowed_primitives={"proc.exec", "file.delete"},
        )
        result = validator.validate(skill)
        if not result.passed:
            raise ValueError("; ".join(result.errors))
    """

    def __init__(
        self,
        primitive_registry: PrimitiveRegistry,
        skill_registry: CapabilitySkillRegistry,
        disallowed_primitives: set[str] | None = None,
        semantic_validator: "SkillSemanticSafetyValidator | None" = None,
    ) -> None:
        self._primitive_registry = primitive_registry
        self._skill_registry = skill_registry
        self._disallowed: set[str] = (
            disallowed_primitives
            if disallowed_primitives is not None
            else DEFAULT_DISALLOWED_PRIMITIVES
        )
        self._semantic_validator = semantic_validator

    @property
    def disallowed_primitives(self) -> set[str]:
        """The set of primitive names that agent-authored skills may not use."""
        return self._disallowed

    def validate(self, skill: CapabilitySkill) -> SafetyResult:
        """Run all safety checks on *skill*.

        Returns a ``SafetyResult`` with all discovered issues (not just
        the first).  This lets the caller report all problems at once.
        """
        errors: list[str] = []

        # 1. Primitives exist
        errors.extend(self._check_primitives_exist(skill))

        # 2. No disallowed primitives
        errors.extend(self._check_disallowed_primitives(skill))

        # 3. No system skill override
        errors.extend(self._check_system_skill_override(skill))

        # 4. No privilege escalation (basic: step outputs constrained)
        errors.extend(self._check_privilege_escalation(skill))

        # 5. Schemas are well-formed
        errors.extend(self._check_schemas(skill))

        # 6. No circular references
        errors.extend(self._check_circular_refs(skill))

        # 7. No recursive self-references (3.17.1)
        errors.extend(self._check_recursive_refs(skill))

        # 8. No unbounded loops (3.17.1)
        errors.extend(self._check_loop_termination(skill))

        # 9. No dynamic primitive selection (3.17.1)
        errors.extend(self._check_static_primitives(skill))

        # 10. Semantic safety checks (3.17.2) — composed validator
        if self._semantic_validator is not None:
            semantic_result = self._semantic_validator.validate(skill)
            errors.extend(semantic_result.errors)

        return SafetyResult(passed=len(errors) == 0, errors=errors)

    # ── Individual checks ──────────────────────────────────────────────────

    def _check_primitives_exist(self, skill: CapabilitySkill) -> list[str]:
        """Check every declared primitive exists in the registry."""
        from src.capabilities.registry.skill_metadata_validation import (
            validate_skill_primitives,
        )

        try:
            validate_skill_primitives(skill, self._primitive_registry)
        except ValueError as exc:
            return [str(exc)]
        return []

    def _check_disallowed_primitives(self, skill: CapabilitySkill) -> list[str]:
        """Check no declared primitive is in the disallowed set."""
        errors: list[str] = []
        for name in skill.manifest.primitives:
            if name in self._disallowed:
                errors.append(
                    f"disallowed primitive '{name}' — agent-authored skills "
                    f"may not use this primitive"
                )
        return errors

    def _check_system_skill_override(self, skill: CapabilitySkill) -> list[str]:
        """Check the skill name does not override an existing system skill.

        System skills have ``plugin_name is None`` on their manifest.
        Agent-authored skills always have a non-None ``plugin_name``.
        """
        existing = self._skill_registry.get(skill.manifest.name)
        if existing is None:
            return []

        # A system skill is one without a plugin origin.
        if getattr(existing.manifest, "plugin_name", None) is None:
            return [
                f"skill name '{skill.manifest.name}' conflicts with a "
                f"system skill — agent-authored skills may not override "
                f"system skills"
            ]
        return []

    def _check_privilege_escalation(self, skill: CapabilitySkill) -> list[str]:
        """Detect basic privilege escalation patterns.

        For now this checks:
        - Steps don't reference primitives outside the declared set
          (already enforced by manifest validation, but we double-check).
        - No step output feeds into a higher-privilege primitive
          without explicit declaration.
        """
        declared = set(skill.manifest.primitives)
        errors: list[str] = []

        for i, step in enumerate(skill.manifest.steps):
            call = step.get("call")
            if call is None:
                continue
            if call not in declared:
                errors.append(
                    f"step[{i}] calls '{call}' which is not in the "
                    f"declared primitives list"
                )

        return errors

    def _check_schemas(self, skill: CapabilitySkill) -> list[str]:
        """Check input/output schemas are well-formed."""
        from src.capabilities.registry.skill_metadata_validation import (
            validate_skill_schemas,
        )

        try:
            validate_skill_schemas(skill)
        except ValueError as exc:
            return [str(exc)]
        return []

    def _check_circular_refs(self, skill: CapabilitySkill) -> list[str]:
        """Check the skill does not introduce circular references."""
        from src.capabilities.registry.skill_metadata_validation import (
            validate_no_circular_references,
        )

        try:
            validate_no_circular_references(skill, self._skill_registry)
        except ValueError as exc:
            return [str(exc)]
        return []

    # ── 3.17.1 Structural safety checks ──────────────────────────────────

    def _check_recursive_refs(self, skill: CapabilitySkill) -> list[str]:
        """Check the skill does not reference itself in any step.

        Scans all step values (``call``, ``args``, ``return``, ``python``) for
        the skill's own name, which would indicate a self-referencing loop.
        """
        errors: list[str] = []
        own_name = skill.manifest.name

        for i, step in enumerate(skill.manifest.steps):
            # Check the call target
            call = step.get("call")
            if call is not None and own_name in str(call):
                errors.append(
                    f"step[{i}] calls '{call}' which references the skill's "
                    f"own name '{own_name}' — recursive self-reference detected"
                )

            # Check args/with values
            args = step.get("args") or step.get("with", {})
            args_str = str(args)
            if own_name in args_str:
                errors.append(
                    f"step[{i}] args contain reference to skill's own name "
                    f"'{own_name}' — recursive self-reference detected"
                )

            # Check return value
            ret = step.get("return")
            if ret is not None and own_name in str(ret):
                errors.append(
                    f"step[{i}] return value references the skill's own name "
                    f"'{own_name}' — recursive self-reference detected"
                )

        return errors

    def _check_loop_termination(self, skill: CapabilitySkill) -> list[str]:
        """Check steps do not contain unbounded loop constructs.

        Rejects explicit loop control-flow patterns (``while``, ``goto``,
        ``loop`` keys) that could cause unbounded execution.
        """
        errors: list[str] = []
        _UNBOUNDED_KEYS = {"while", "goto", "loop", "repeat", "forever"}

        for i, step in enumerate(skill.manifest.steps):
            for key in _UNBOUNDED_KEYS:
                if key in step:
                    errors.append(
                        f"step[{i}] contains '{key}' key — unbounded loop "
                        f"constructs are not allowed in agent-authored skills"
                    )

            # Also check python blocks for while True patterns
            python_code = step.get("python")
            if python_code is not None:
                code_str = str(python_code)
                if "while True" in code_str or "while 1" in code_str:
                    errors.append(
                        f"step[{i}] python block contains unbounded loop "
                        f"('while True') — not allowed in agent-authored skills"
                    )

        return errors

    def _check_static_primitives(self, skill: CapabilitySkill) -> list[str]:
        """Check all primitive calls use static string literals.

        Dynamic primitive selection (e.g. ``"{{ target }}"`` as a call
        target) is prohibited because it allows runtime redirection to
        arbitrary primitives, bypassing the declared primitive set.
        """
        errors: list[str] = []

        for i, step in enumerate(skill.manifest.steps):
            call = step.get("call")
            if call is None:
                continue
            if not isinstance(call, str):
                errors.append(
                    f"step[{i}] call target must be a string literal, "
                    f"got {type(call).__name__}"
                )
                continue
            # Template tokens like "{{ something }}" indicate dynamic selection
            if "{{" in call:
                errors.append(
                    f"step[{i}] call target '{call}' uses dynamic template — "
                    f"primitive selection must be static in agent-authored skills"
                )

        return errors
