"""
Phase 3.6.2 — Deterministic skill ranking for semantic discovery.

Ranks discovered skills using a strict, ordered, deterministic scoring
pipeline:  exact tag match → schema compatibility → safety level →
determinism → cost → embedding similarity → name (tiebreaker).

This ensures S2 always selects the same skill for the same query.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.capabilities.registry.skill_discovery_result import SkillSearchResult
    from src.capabilities.skills.skill import CapabilitySkill as Skill


# ── Known capability tags ───────────────────────────────────────────

_KNOWN_TAGS: set[str] = {
    "fetch",
    "parse",
    "transform",
    "validate",
    "compute",
    "notify",
    "store",
    "delete",
    "search",
    "generate",
    "execute",
    "read",
    "write",
    "sync",
    "auth",
    "upload",
    "download",
    "encode",
    "decode",
    "summarise",
    "summarize",
}

# ── Ranking constants ───────────────────────────────────────────────

_SAFETY_RANK: dict[str, int] = {"high": 3, "medium": 2, "low": 1}
_DET_RANK: dict[str, int] = {"pure": 3, "impure": 2, "nondeterministic": 1}
_RES_RANK: dict[str, int] = {"low": 3, "medium": 2, "high": 1}


# ── Public API ──────────────────────────────────────────────────────

def rank_discovered_skills(
    query: str,
    results: List["SkillSearchResult"],
    context: Optional[Dict[str, Any]] = None,
) -> List["SkillSearchResult"]:
    """Apply the deterministic ranking pipeline to *results*.

    Priority order (highest to lowest):
      A. exact tag match
      B. schema compatibility
      C. safety level
      D. determinism
      E. cost estimate
      F. embedding similarity
      G. name (final tiebreaker)

    Args:
        query: The original search query.
        results: Unsorted ``SkillSearchResult`` items.
        context: Optional dict with ``input_hints`` / ``output_hints``.

    Returns:
        The same list, sorted deterministically.
    """
    ctx = context or {}

    def _sort_key(result: SkillSearchResult) -> tuple:
        skill = result.skill
        meta = skill.manifest.metadata  # SkillManifestMetadata

        # A.  Exact tag match
        tag_score = _compute_tag_score(query, meta.tags)

        # B.  Schema compatibility
        schema_score = compute_schema_compatibility(query, skill, ctx)

        # C.  Safety level
        safety_rank = _SAFETY_RANK.get(meta.safety_level, 0)

        # D.  Determinism
        det_rank = _DET_RANK.get(meta.determinism, 0)

        # E.  Cost estimate  (lower latency → better; higher resource rank → better)
        latency = meta.cost_estimate.get("latency", 0)
        resources = meta.cost_estimate.get("resources", "unknown")
        res_rank = _RES_RANK.get(resources, 0)
        cost_score = (-latency, res_rank)

        # F.  Embedding similarity (already computed)
        # G.  Name (final tiebreaker)
        return (
            -tag_score,           # negate so higher scores sort first
            -schema_score,
            -safety_rank,
            -det_rank,
            cost_score[0],        # -latency  (more negative = larger latency = worse)
            -cost_score[1],       # -res_rank
            -result.score,
            result.name,
        )

    return sorted(results, key=_sort_key)


def compute_schema_compatibility(
    query: str,
    skill: "Skill",
    context: Dict[str, Any],
) -> int:
    """Count matching fields between context hints and skill manifest metadata.

    Args:
        query: The original search query  (unused — reserved for future use).
        skill: The runtime ``CapabilitySkill`` being scored.
        context: May contain ``input_hints`` and/or ``output_hints`` dicts.

    Returns:
        Integer score — strictly the count of matching field names.
    """
    score = 0
    meta = skill.manifest.metadata  # SkillManifestMetadata

    for hint_key, meta_dict in [
        ("input_hints", meta.input_types),
        ("output_hints", meta.output_types),
    ]:
        hints = context.get(hint_key)
        if not isinstance(hints, dict):
            continue
        for field_name in hints:
            if field_name in meta_dict:
                score += 1

    return score


def extract_query_tag(query: str) -> Optional[str]:
    """Return the first known capability tag found in *query*, or ``None``.

    This is a simple substring membership check — no NLP, no fuzzy
    matching, fully deterministic.

    Args:
        query: The user's search query string.

    Returns:
        A known tag string, or ``None`` if no tag is present.
    """
    lower = query.lower()
    for tag in sorted(_KNOWN_TAGS, key=len, reverse=True):
        if tag in lower:
            return tag
    return None


# ── Internal helpers ────────────────────────────────────────────────

def _compute_tag_score(query: str, tags: List[str]) -> int:
    """Compute exact tag match score.

    Each tag in *tags* that appears as a substring of *query* contributes 1.
    """
    lower = query.lower()
    return sum(1 for t in tags if t.lower() in lower)
