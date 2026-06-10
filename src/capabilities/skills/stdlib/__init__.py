"""
stdlib skills — auto-discovery loader (Phase 2.18.5).

Import ``load_all_skills`` to scan this directory for ``*.skill.md``
files, parse their YAML frontmatter into ``SkillManifest`` objects, resolve
primitives via a ``PrimitiveRegistry``, build ``CapabilitySkill`` instances,
and register them into a ``CapabilitySkillRegistry``.

Usage::

    from src.capabilities.skills.stdlib import load_all_skills
    from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry

    prim_registry = PrimitiveRegistry()
    skill_registry = CapabilitySkillRegistry()

    load_all_primitives(prim_registry)  # from primitives.stdlib
    count = load_all_skills(skill_registry, prim_registry)
    print(f"Registered {count} stdlib skills")

**PHASE 3.19.2**: If an embedder is provided it is set on the registry
before loading so that every skill receives a pre‑computed embedding.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill

if TYPE_CHECKING:
    from src.capabilities.discovery.embedder import SkillEmbedder
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry
    from src.capabilities.registry.skill_registry import CapabilitySkillRegistry


_STDLIB_DIR = Path(__file__).resolve().parent


def _extract_yaml_frontmatter(text: str, source: str) -> dict[str, Any]:
    """Extract YAML between ``---`` delimiters from a .skill.md file."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Missing opening --- in {source}")

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        raise ValueError(f"Missing closing --- in {source}")

    yaml_text = "\n".join(lines[1:end_idx])
    return yaml.safe_load(yaml_text)


def load_all_skills(
    skill_registry: CapabilitySkillRegistry,
    prim_registry: PrimitiveRegistry,
    embedder: SkillEmbedder | None = None,
) -> int:
    """Load all ``.skill.md`` files from stdlib into *skill_registry*.

    Parses each skill file, resolves its primitive references against
    *prim_registry*, builds a ``CapabilitySkill``, and registers it.

    **PHASE 3.19.2**: If *embedder* is provided, it is set on the registry
    before loading so that every skill receives a pre‑computed embedding at
    registration time.

    Returns the count of loaded skills.
    """
    if embedder is not None:
        skill_registry.set_embedder(embedder)

    count = 0
    for skill_file in sorted(_STDLIB_DIR.glob("*.skill.md")):
        try:
            raw_text = skill_file.read_text(encoding="utf-8")
            data = _extract_yaml_frontmatter(raw_text, str(skill_file))

            manifest = SkillManifest.from_dict(data)
            skill = CapabilitySkill.from_manifest(manifest, prim_registry)
            skill_registry.register(skill)
            count += 1
        except Exception:
            continue

    return count
