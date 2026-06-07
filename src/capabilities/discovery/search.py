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
from src.capabilities.registry.primitive_registry import SkillRegistry


class SkillSearch:
    """
    Entry point for skill discovery.

    Combines filtering, ranking, and embedding-based semantic search
    to find the best skills matching a discovery query.
    """

    def __init__(
        self,
        registry: Optional[SkillRegistry] = None,
        embedder: Optional[SkillEmbedder] = None,
    ):
        self._registry = registry or SkillRegistry
        self._embedder = embedder or SkillEmbedder()
        self._filter = SkillFilter()
        self._ranker = SkillRanker()

    def search(self, query: SkillDiscoveryQuery) -> SkillDiscoveryResult:
        """
        Search for skills matching the given discovery query.

        Pipeline:
        1. Get all candidate skills from registry
        2. Filter by domain/input/output hints
        3. Rank by relevance to natural-language query
        4. Truncate to max_results
        """
        # Get candidates
        if query.include_disabled:
            candidates = list(self._registry._skills.values())
        else:
            candidates = self._registry.all_specs()

        if not candidates:
            return SkillDiscoveryResult(
                query=query.query,
                skills=[],
                total_count=0,
            )

        # Filter
        if query.domain or query.input_type_hint or query.output_type_hint:
            candidates = self._filter.filter(candidates, query.query or "")

        # Rank
        if query.query:
            ranked = self._ranker.rank(candidates, query.query)
        else:
            ranked = candidates

        total_count = len(ranked)

        # Truncate
        top = ranked[: query.max_results]

        # Build result skills
        discovered = [
            DiscoveredSkill(
                name=spec.name,
                description=spec.description,
                input_schema=spec.schema,
                output_schema=getattr(spec, "output_schema", None),
                domains=getattr(spec, "category", None),
                cost_hint=0,
                relevance_score=1.0,
            )
            for spec in top
        ]

        # Compute relevance scores from embeddings
        if query.query:
            query_vec = self._embedder.embed_query(query.query)
            for i, skill in enumerate(discovered):
                skill_vec = self._embedder.embed_skill(
                    skill.name, skill.description
                )
                score = self._embedder.similarity(query_vec, skill_vec)
                discovered[i].relevance_score = score

        return SkillDiscoveryResult(
            query=query.query,
            skills=discovered,
            total_count=total_count,
        )

    def lookup(self, skill_name: str) -> Optional[DiscoveredSkill]:
        """Look up a single skill by name and return its discovery summary."""
        try:
            spec = self._registry.get(skill_name)
        except KeyError:
            return None

        return DiscoveredSkill(
            name=spec.name,
            description=spec.description,
            input_schema=spec.schema,
            output_schema=getattr(spec, "output_schema", None),
        )
