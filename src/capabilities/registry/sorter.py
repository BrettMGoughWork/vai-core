"""
Deterministic registry sorter (Phase 3.15.1).

Produces a stable, total ordering over skills and primitives so that
identical plugin sets always yield identical registry output,
regardless of insertion order, platform, or Python hash seed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.capabilities.skills.skill import CapabilitySkill
    from src.capabilities.primitives.base import PrimitiveBase


def sorted_skills(skills: list[CapabilitySkill]) -> list[CapabilitySkill]:
    """Return *skills* sorted deterministically.

    Sort order (all ascending):

    1. skill name
    2. plugin version
    3. plugin name
    """
    return sorted(skills, key=_skill_sort_key)


def sorted_primitives(primitives: list[PrimitiveBase]) -> list[PrimitiveBase]:
    """Return *primitives* sorted deterministically.

    Sort order (all ascending):

    1. primitive name
    2. plugin version
    3. plugin name
    """
    return sorted(primitives, key=_primitive_sort_key)


# ── Internal helpers ─────────────────────────────────────────────────


def _skill_sort_key(skill: CapabilitySkill) -> tuple:
    m = skill.manifest
    return (
        m.name or "",
        m.plugin_version or "",
        m.plugin_name or "",
    )


def _primitive_sort_key(p: PrimitiveBase) -> tuple:
    return (
        p.name or "",
        getattr(p, "plugin_version", "") or "",
        getattr(p, "plugin_name", "") or "",
    )
