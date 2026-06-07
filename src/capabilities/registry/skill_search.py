"""
Semantic skill search (Phase 3.4.3).

Standalone functions that rank skills by cosine similarity between
query embeddings and skill embeddings (name + description + step summaries).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from src.capabilities.registry.skill_embeddings import (
    build_query_embedding,
    build_skill_embedding,
)

if TYPE_CHECKING:
    from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
    from src.capabilities.skills.skill import CapabilitySkill


def search_skills(
    query: str,
    registry: "CapabilitySkillRegistry",
    context: dict,
) -> list[dict]:
    """Search the registry for skills matching *query* via embeddings.

    Args:
        query: Natural-language description of the desired capability.
        registry: ``CapabilitySkillRegistry`` containing registered skills.
        context: Must contain an ``"embedding_fn"`` key whose value is a
                 callable that accepts a string and returns a list of floats.

    Returns:
        A list of match dicts (``name``, ``skill``, ``score``) sorted
        descending by cosine similarity.  Zero‑score matches are excluded.

    Raises:
        ValueError: If ``"embedding_fn"`` is missing from *context*.
    """
    q_embedding = build_query_embedding(query, context)

    matches: list[dict] = []
    for skill in registry.list():
        skill_embedding = build_skill_embedding(skill, context)
        similarity = cosine_similarity(q_embedding, skill_embedding)

        if similarity > 0:
            matches.append({
                "name": skill.manifest.name,
                "skill": skill,
                "score": similarity,
            })

    matches.sort(key=lambda m: m["score"], reverse=True)
    return matches


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute the cosine similarity between two vectors.

    Returns 0.0 if either vector has zero magnitude.
    """
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    return dot / (norm1 * norm2) if norm1 and norm2 else 0.0
