"""
Skill metadata validation (Phase 3.4.4).

Registration‑time validation ensuring primitive references resolve,
schemas are well‑formed, and no circular skill references exist.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry
    from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
    from src.capabilities.skills.skill import CapabilitySkill


def validate_skill_primitives(
    skill: "CapabilitySkill", registry: "PrimitiveRegistry"
) -> None:
    """Validate that all primitive references in *skill* resolve.

    Args:
        skill: The ``CapabilitySkill`` whose primitives to validate.
        registry: ``PrimitiveRegistry`` used to look up primitive names.

    Raises:
        ValueError: If a declared primitive is unknown, or a step
                    references an undeclared primitive.
    """
    declared = set(skill.manifest.primitives)

    for name in declared:
        if registry.get(name) is None:
            raise ValueError(f"unknown primitive: {name}")

    for step in skill.manifest.steps:
        call = step.get("call")
        if call and call not in declared:
            raise ValueError("step references undeclared primitive")


def validate_skill_schemas(skill: "CapabilitySkill") -> None:
    """Validate input and output schemas for structural correctness.

    Args:
        skill: The ``CapabilitySkill`` whose schemas to validate.

    Raises:
        ValueError: If either schema is not a dict, has non‑string keys,
                    or contains non‑JSON‑serializable values.
    """
    _validate_schema_dict(skill.input_schema, "input")
    _validate_schema_dict(skill.output_schema, "output")


def validate_no_circular_references(
    skill: "CapabilitySkill", registry: "CapabilitySkillRegistry"
) -> None:
    """Detect circular skill references introduced by *skill*.

    A skill depends on another skill when any step's ``call`` matches
    another skill's name.  Uses DFS to detect cycles.

    Args:
        skill: The ``CapabilitySkill`` being registered.
        registry: ``CapabilitySkillRegistry`` containing all skills.

    Raises:
        ValueError: If registering *skill* would create a cycle.
    """
    # Build adjacency list: skill_name → [depended_skill_names]
    graph: dict[str, list[str]] = {}
    all_skills = registry.list() + [skill]

    for s in all_skills:
        name = s.manifest.name
        deps: list[str] = []
        for step in s.manifest.steps:
            call = step.get("call", "")
            # A step references a skill if its call matches another skill's name
            if call and any(call == other.manifest.name for other in all_skills):
                deps.append(call)
        graph[name] = deps

    # DFS cycle detection from the new skill
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def _dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if _dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                return True
        rec_stack.discard(node)
        return False

    if _dfs(skill.manifest.name):
        raise ValueError("circular skill reference detected")


# ── helpers ──────────────────────────────────────────────────────────────


def _validate_schema_dict(schema: dict, label: str) -> None:
    """Validate that *schema* is a well‑formed schema dict."""
    if not isinstance(schema, dict):
        raise ValueError(f"invalid {label} schema")
    for key in schema:
        if not isinstance(key, str):
            raise ValueError(f"invalid {label} schema")
    _check_json_serializable(schema, label)


def _check_json_serializable(value: object, label: str) -> None:
    """Best‑effort check that *value* is JSON‑serializable."""
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid {label} schema")
