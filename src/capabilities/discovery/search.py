"""
Skill discovery search (Phase 3.0.1).

Provides search and ranking for skill discovery queries.
Incorporates the existing SkillRanker and SkillFilter logic
from the old primitives/runtime/ location.
"""

from __future__ import annotations

from typing import Any, List, Optional

from src.capabilities.contracts import (
    DiscoveredSkill,
    SkillDiscoveryQuery,
    SkillDiscoveryResult,
)
from src.capabilities.discovery.embedder import SkillEmbedder
from src.capabilities.discovery.skill_filter import SkillFilter
from src.capabilities.discovery.skill_ranker import SkillRanker
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry


class SkillSearch:
    """
    Entry point for skill discovery.

    Combines filtering, ranking, and embedding-based semantic search
    to find the best skills matching a discovery query.
    """

    def __init__(
        self,
        registry: Optional[CapabilitySkillRegistry] = None,
        embedder: Optional[SkillEmbedder] = None,
    ):
        self._registry = registry or CapabilitySkillRegistry
        self._embedder = embedder or SkillEmbedder()
        self._filter = SkillFilter()
        self._ranker = SkillRanker()

    def search(self, query: SkillDiscoveryQuery) -> SkillDiscoveryResult:
        """
        Search for skills matching the given discovery query.

        Pipeline:
        1. Get all candidate skills from registry
        2. Rank by relevance to natural-language query
        3. Truncate to query.limit
        """
        candidates = self._registry.all_specs()

        if not candidates:
            return SkillDiscoveryResult(query=query, skills=[])

        # Rank candidates by relevance to the query text
        ranked = self._ranker.rank(candidates, query.query)

        # Truncate to limit
        top = ranked[: query.limit]

        # Compute embedding-based scores
        query_vec = self._embedder.embed_query(query.query)
        scored: list[tuple[float, DiscoveredSkill]] = []
        for spec in top:
            skill_vec = self._embedder.embed_skill(spec.name, spec.description)
            score = self._embedder.similarity(query_vec, skill_vec)
            scored.append((
                score,
                DiscoveredSkill(
                    name=spec.name,
                    description=spec.description,
                    score=score,
                ),
            ))

        # Sort by descending score
        scored.sort(key=lambda s: s[0], reverse=True)
        skills = [s[1] for s in scored]

        return SkillDiscoveryResult(query=query, skills=skills)

    def lookup(self, skill_name: str) -> Optional[DiscoveredSkill]:
        """Look up a single skill by name and return its discovery summary."""
        try:
            spec = self._registry.get(skill_name)
        except KeyError:
            return None

        return DiscoveredSkill(
            name=spec.name,
            description=spec.description,
        )
