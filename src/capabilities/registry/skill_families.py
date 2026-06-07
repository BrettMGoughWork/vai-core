"""
Phase 3.6.3 — Skill family grouping.

Groups skills into deterministic families based on manifest metadata and
name prefixes:  fetch.*, file.*, parse.*, transform.*, browser.*.

These families help S2 reason about alternatives, fallbacks, and
plan‑level substitution.
"""
from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.capabilities.registry.skill_discovery_result import SkillSearchResult
    from src.capabilities.skills.skill import CapabilitySkill as Skill


# ── Canonical families ──────────────────────────────────────────────

_CANONICAL_FAMILIES: List[str] = [
    "fetch",
    "file",
    "parse",
    "transform",
    "browser",
    "generic",
]

# The first five are also valid tag names for tag‑based fallback.
_TAG_FAMILIES: set[str] = {"fetch", "file", "parse", "transform", "browser"}


# ── Public API ──────────────────────────────────────────────────────

def infer_skill_family(skill: "Skill") -> str:
    """Determine the family of *skill* using strict deterministic rules.

    Priority:
      A.  Name‑based prefix detection  (e.g. ``"fetch.foo"`` → ``"fetch"``)
      B.  Tag‑based fallback  (manifest metadata tags)
      C.  Default — ``"generic"``

    Args:
        skill: The runtime ``CapabilitySkill``.

    Returns:
        One of the canonical family strings.
    """
    # A.  Name‑based prefix
    name = skill.manifest.name
    for family in _CANONICAL_FAMILIES[: -1]:  # all except "generic"
        prefix = family + "."
        if name.startswith(prefix):
            return family

    # B.  Tag‑based fallback
    meta = getattr(skill.manifest, "metadata", None)
    if meta is not None:
        for tag in meta.tags:
            if tag in _TAG_FAMILIES:
                return tag

    # C.  Default
    return "generic"


def group_skills_by_family(
    skills: List["Skill"],
) -> Dict[str, List["Skill"]]:
    """Group *skills* by their inferred family.

    Families always appear in canonical order.  Skills within each
    family are sorted alphabetically by ``skill.manifest.name`` for
    determinism.

    Args:
        skills: Unsorted list of ``CapabilitySkill`` instances.

    Returns:
        A dict mapping family name → sorted skill list.
    """
    # Start with empty lists in canonical order.
    groups: Dict[str, List["Skill"]] = {f: [] for f in _CANONICAL_FAMILIES}

    for skill in skills:
        family = infer_skill_family(skill)
        groups[family].append(skill)

    # Deterministic sort within each family.
    for family in _CANONICAL_FAMILIES:
        groups[family].sort(key=lambda s: s.manifest.name)

    return groups


def attach_family_to_discovery_result(result: "SkillSearchResult") -> None:
    """Compute and attach the family to ``result`` in‑place.

    The family is stored as ``result.family``.  No other fields are
    mutated.

    Args:
        result: A ``SkillSearchResult`` returned from semantic search.
    """
    family = infer_skill_family(result.skill)
    result.family = family  # type: ignore[attr-defined]
