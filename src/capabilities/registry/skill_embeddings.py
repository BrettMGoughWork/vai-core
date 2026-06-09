"""
Skill embedding generation (Phase 3.4.2).

Builds deterministic embedding texts from skill manifests and generates
vector embeddings for use by ``CapabilitySkillRegistry.find()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.capabilities.skills.skill import CapabilitySkill


def build_skill_embedding(skill: "CapabilitySkill", context: dict) -> list[float]:
    """Generate an embedding vector for a skill.

    The embedding text combines the skill name, description, and a
    deterministic summary of every execution step.

    Args:
        skill: A fully constructed ``CapabilitySkill``.
        context: Must contain an ``"embedding_fn"`` key whose value is a
                 callable that accepts a string and returns a list of floats.

    Returns:
        A list of floats representing the embedding vector.

    Raises:
        ValueError: If ``"embedding_fn"`` is missing from *context*.
    """
    embedding_fn = context.get("embedding_fn")
    if embedding_fn is None:
        raise ValueError("missing embedding_fn")

    text = _build_skill_text(skill)
    return embedding_fn(text)


def build_query_embedding(query: str, context: dict) -> list[float]:
    """Generate an embedding vector for a search query.

    Args:
        query: Natural-language search query.
        context: Must contain an ``"embedding_fn"`` key whose value is a
                 callable that accepts a string and returns a list of floats.

    Returns:
        A list of floats representing the query embedding vector.

    Raises:
        ValueError: If ``"embedding_fn"`` is missing from *context*.
    """
    embedding_fn = context.get("embedding_fn")
    if embedding_fn is None:
        raise ValueError("missing embedding_fn")

    return embedding_fn(query)


def _build_skill_text(skill: "CapabilitySkill") -> str:
    """Construct a deterministic text block representing the skill.

    Combines the skill name, description, step summaries, and a
    deterministic signature derived from the input / output schemas.
    """
    lines = [skill.manifest.name, skill.manifest.description]

    # ── Signature (Phase 3.19.2) ──────────────────────────────────────
    sig = _build_signature(skill)
    if sig:
        lines.append(f"signature: {sig}")

    # ── Step summaries ────────────────────────────────────────────────
    for step in skill.manifest.steps:
        call = step.get("call", "")
        args_keys = sorted(step.get("args", {}).keys())
        args_summary = ",".join(args_keys)
        lines.append(f"step: {call} args: {args_summary}")

    return "\n".join(lines)


def _build_signature(skill: "CapabilitySkill") -> str:
    """Build a deterministic function‑like signature from I/O schemas.

    Example:
        ``(query: str, max_results: number) -> SearchResult[]``
    """
    in_props: dict = (skill.manifest.inputs or {}).get("properties", {})
    out_props: dict = getattr(skill.manifest, "outputs", {}) or {}
    out_props = out_props.get("properties", {}) if isinstance(out_props, dict) else {}

    # Input side
    in_parts: list[str] = []
    for key, prop in sorted(in_props.items()):
        ptype = prop.get("type", "any") if isinstance(prop, dict) else "any"
        in_parts.append(f"{key}:{ptype}")

    # Output side
    out_parts: list[str] = []
    for key, prop in sorted(out_props.items()):
        ptype = prop.get("type", "any") if isinstance(prop, dict) else "any"
        out_parts.append(f"{key}:{ptype}")

    in_str = ", ".join(in_parts)
    out_str = ", ".join(out_parts)

    if not in_str and not out_str:
        return ""

    if out_str:
        return f"({in_str})->({out_str})"
    return f"({in_str})"
