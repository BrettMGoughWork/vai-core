"""
Discovery fallback wiring (Phase 3.19.5).

Integrates semantic vector search into the S2/S3 discovery pipeline
as a LAST-RESORT fallback when the LLM fails to name a capability or
names a non-existent one.  LLM-selected skills ALWAYS take precedence.

The ``resolve_capability_with_fallback`` function is the single entry
point used by the SkillRunner and S2/S3 planner to resolve a
capability name, falling back to semantic search when needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.capabilities.skills.skill import CapabilitySkill
    from src.capabilities.registry.skill_registry import CapabilitySkillRegistry


async def resolve_capability_with_fallback(
    query: str,
    llm_named: str | None,
    registry: "CapabilitySkillRegistry",
    k: int = 1,
) -> "CapabilitySkill | None":
    """Resolve a capability name, falling back to semantic search if needed.

    **PHASE 3.19.5**: This is the single wiring point for discovery
    fallback.  It is called from the SkillRunner and S2/S3 planner
    whenever a skill name needs resolution.

    Behavior:
        * If *llm_named* is not ``None`` AND exists in the registry
          → return it directly.  LLM-chosen skills always win.
        * If *llm_named* is ``None`` OR does not exist in the registry
          → embed *query* using the registry's configured embedder
          → run ``find_semantic(query, top_k=k)``
          → return the top match (or ``None`` if none found).

    Constraints:
        * No heuristics — pure semantic search fallback.
        * No fuzzy matching on skill names.
        * No rewriting of *query*.
        * No cross-skill inference.
        * No network calls in unit tests (use mock provider).

    Args:
        query: Natural-language description of the desired capability.
               Used as the embedding query when fallback is triggered.
        llm_named: The skill name the LLM provided, or ``None`` if the
                   LLM failed to name any capability.
        registry: The skill registry to search.
        k: Maximum number of results to consider (default 1).

    Returns:
        The resolved ``CapabilitySkill``, or ``None`` if no match was
        found via either direct lookup or semantic fallback.
    """
    # ── Direct match: LLM-named skill exists ──────────────────────
    if llm_named is not None:
        direct = registry.get(llm_named)
        if direct is not None:
            return direct

    # ── Semantic fallback: embed query & search ───────────────────
    try:
        results = registry.find_semantic(query, k=k)
    except (ValueError, Exception):
        # No embedder configured or search failed → no fallback possible
        return None

    _MIN_SIMILARITY = 0.35  # reject matches too dissimilar to the query
    if results and results[0][1] >= _MIN_SIMILARITY:
        return results[0][0]  # top-match skill

    return None
