"""
Phase 3.5.3 — S2 metadata consumption points.

S2 calls these functions during skill discovery, plan generation,
segment construction, repair decisions, drift detection, and
reflection.  They are pure read functions — no mutation, no
inference, no execution.
"""
from __future__ import annotations

from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from src.capabilities.registry.skill_discovery_result import (
        SkillSearchResult,
        PrimitiveMetadataExport,
    )
    from src.capabilities.skills.skill import CapabilitySkill as Skill


def consume_discovery_metadata(result: "SkillSearchResult") -> Dict[str, Any]:
    """Consume a ``SkillSearchResult`` for downstream S2 use.

    Used immediately after semantic skill search.

    Args:
        result: A ``SkillSearchResult`` from the S3 discovery pipeline.

    Returns:
        A JSON‑serializable dict with name, score, skill_metadata,
        flattened primitive_metadata, and version.
    """
    return {
        "name": result.name,
        "score": result.score,
        "skill_metadata": dict(result.skill_metadata),
        "primitive_metadata": [
            _flatten_primitive_export(pe) for pe in result.primitive_metadata
        ],
        "version": "1.0",
    }


def consume_for_plan_generation(result: "SkillSearchResult") -> Dict[str, Any]:
    """Extract planning‑relevant metadata from a discovery result.

    Used when S2 selects skills for inclusion in a plan.

    Args:
        result: A ``SkillSearchResult`` from the S3 discovery pipeline.

    Returns:
        A JSON‑serializable dict with cost, determinism, safety_level,
        prerequisites, and failure_modes.
    """
    sm = result.skill_metadata
    return {
        "name": result.name,
        "cost": {
            "latency_ms": sm.get("cost_latency", 0),
            "resources": sm.get("cost_resources", "unknown"),
        },
        "determinism": sm.get("determinism", "unknown"),
        "safety_level": sm.get("safety_level", "unknown"),
        "prerequisites": list(sm.get("prerequisites", [])),
        "failure_modes": list(sm.get("failure_modes", [])),
        "version": "1.0",
    }


def consume_for_segment_construction(
    skill: "Skill",
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Build segment‑level metadata for plan construction.

    Used when S2 builds plan segments from selected skills.

    Args:
        skill: The runtime ``CapabilitySkill`` being assembled.
        metadata: The planning metadata dict returned by
                  ``consume_for_plan_generation``.

    Returns:
        A JSON‑serializable dict describing output schema,
        side‑effects, determinism, prerequisites, and safety_level.
    """
    sm = skill.metadata  # type: ignore[attr-defined]
    return {
        "output_schema": dict(sm.output_schema),
        "side_effects": list(sm.side_effects),
        "determinism": metadata.get("determinism", "unknown"),
        "prerequisites": list(metadata.get("prerequisites", [])),
        "safety_level": metadata.get("safety_level", "unknown"),
    }


def consume_for_repair_and_reflection(
    skill: "Skill",
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Build metadata for repair, drift‑detection, and reflection.

    Used when S2 repairs execution failures, detects drift, or
    reflects on plan outcomes.

    Args:
        skill: The runtime ``CapabilitySkill`` being evaluated.
        metadata: The planning metadata dict returned by
                  ``consume_for_plan_generation``.

    Returns:
        A JSON‑serializable dict with failure_modes, determinism,
        side_effects, prerequisites, safety_level, output_schema,
        and version.
    """
    sm = skill.metadata  # type: ignore[attr-defined]
    return {
        "failure_modes": list(sm.failure_modes),
        "determinism": metadata.get("determinism", "unknown"),
        "side_effects": list(sm.side_effects),
        "prerequisites": list(metadata.get("prerequisites", [])),
        "safety_level": metadata.get("safety_level", "unknown"),
        "output_schema": dict(sm.output_schema),
        "version": "1.0",
    }


# ── helpers ────────────────────────────────────────────────────────────────

def _flatten_primitive_export(pe: "PrimitiveMetadataExport") -> Dict[str, Any]:
    """Convert a ``PrimitiveMetadataExport`` to a flat JSON‑serializable dict."""
    return {
        "name": pe.name,
        "version": pe.version,
        "cost_latency": pe.cost_latency,
        "cost_resources": pe.cost_resources,
        "determinism": pe.determinism,
        "side_effects": list(pe.side_effects),
        "output_schema": dict(pe.output_schema),
        "failure_modes": list(pe.failure_modes),
        "safety_level": pe.safety_level,
        "prerequisites": list(pe.prerequisites),
    }
