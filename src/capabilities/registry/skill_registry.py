"""
Skill registry (Phase 3.4.1).

Deterministic registry for storing, retrieving, listing, and semantically
discovering S3 ``CapabilitySkill`` objects via embeddings.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from src.capabilities.skills.skill import CapabilitySkill


class CapabilitySkillRegistry:
    """Deterministic registry for S3 CapabilitySkill objects."""

    def __init__(self) -> None:
        self._skills: dict[str, CapabilitySkill] = {}

    def register(self, skill: "CapabilitySkill") -> None:
        """Register a skill.

        The key is ``skill.manifest.name``.

        Raises:
            ValueError: If a skill with the same name is already registered.
        """
        name = skill.manifest.name
        if name in self._skills:
            raise ValueError(f"Skill '{name}' is already registered")
        self._skills[name] = skill

    def get(self, name: str) -> "CapabilitySkill | None":
        """Return the skill registered under *name*, or ``None`` if not found."""
        return self._skills.get(name)

    def list(
        self, filter: Callable[["CapabilitySkill"], bool] | None = None
    ) -> list["CapabilitySkill"]:
        """Return all skills, optionally filtered by *filter*."""
        if filter is None:
            return list(self._skills.values())
        return [s for s in self._skills.values() if filter(s)]

    def find(self, query: str, context: dict) -> list[dict]:
        """Semantic discovery via embeddings.

        Args:
            query: Natural-language description of the desired capability.
            context: Must contain an ``"embedding_fn"`` key whose value is a
                     callable that accepts a string and returns a list of floats.

        Returns:
            A list of match dicts (``name``, ``skill``, ``score``) sorted
            descending by cosine similarity.  Zero‑score matches are excluded.

        Raises:
            ValueError: If ``"embedding_fn"`` is missing from *context*.
        """
        embedding_fn = context.get("embedding_fn")
        if embedding_fn is None:
            raise ValueError("missing embedding_fn")

        query_embedding = embedding_fn(query)

        matches: list[dict] = []
        for skill in self._skills.values():
            text = f"{skill.manifest.name}\n{skill.manifest.description}"
            skill_embedding = embedding_fn(text)
            similarity = _cosine_similarity(query_embedding, skill_embedding)

            if similarity > 0:
                matches.append({
                    "name": skill.manifest.name,
                    "skill": skill,
                    "score": similarity,
                })

        matches.sort(key=lambda m: m["score"], reverse=True)
        return matches


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Return the cosine similarity between two vectors.

    Returns 0.0 if either vector has zero magnitude.
    """
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    return dot / (norm1 * norm2) if norm1 and norm2 else 0.0
