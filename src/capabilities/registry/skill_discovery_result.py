"""
Phase 3.5.2 — Metadata export for semantic skill discovery.

When S2 performs semantic discovery, S3 returns SkillSearchResult
objects that include skill metadata and primitive metadata for all
referenced primitives.  Metadata is deterministic, JSON‑serializable,
and versioned.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from src.capabilities.skills.skill import CapabilitySkill as Skill
    from src.capabilities.metadata.capability_metadata import (
        PrimitiveMetadata,
        CapabilitySkillMetadata,
    )


@dataclass
class PrimitiveMetadataExport:
    """Exported metadata for a single primitive."""

    name: str
    version: str
    cost_latency: int
    cost_resources: str
    determinism: str
    side_effects: List[str]
    output_schema: Dict[str, Any]
    failure_modes: List[str]
    safety_level: str
    prerequisites: List[str]

    @classmethod
    def from_primitive(
        cls,
        name: str,
        metadata: "PrimitiveMetadata",
    ) -> "PrimitiveMetadataExport":
        return cls(
            name=name,
            version="1.0",
            cost_latency=metadata.cost_latency,
            cost_resources=metadata.cost_resources,
            determinism=metadata.determinism,
            side_effects=list(metadata.side_effects),
            output_schema=dict(metadata.output_schema),
            failure_modes=list(metadata.failure_modes),
            safety_level=metadata.safety_level,
            prerequisites=list(metadata.prerequisites),
        )


@dataclass
class SkillSearchResult:
    """A discovered skill returned during semantic search.

    Includes skill metadata and primitive metadata for all referenced
    primitives.  The ``skill`` field is included for runtime use and is
    not JSON‑serialized.
    """

    name: str
    score: float
    version: str
    skill_metadata: Dict[str, Any]
    primitive_metadata: List[PrimitiveMetadataExport]
    skill: "Skill" = field(repr=False)


def build_discovery_result(skill: "Skill", score: float) -> SkillSearchResult:
    """Build a ``SkillSearchResult`` from a skill and its relevance score.

    Args:
        skill: A runtime‑ready ``CapabilitySkill`` with metadata attached.
        score: Relevance score from semantic search (0.0–1.0).

    Returns:
        ``SkillSearchResult`` with exported metadata for S2 consumption.
    """
    skill_meta = skill.metadata  # type: ignore[attr-defined]

    skill_meta_dict: Dict[str, Any] = {
        "version": "1.0",
        "cost_latency": skill_meta.cost_latency,
        "cost_resources": skill_meta.cost_resources,
        "determinism": skill_meta.determinism,
        "side_effects": list(skill_meta.side_effects),
        "output_schema": dict(skill_meta.output_schema),
        "failure_modes": list(skill_meta.failure_modes),
        "safety_level": skill_meta.safety_level,
        "prerequisites": list(skill_meta.prerequisites),
    }

    primitive_exports: List[PrimitiveMetadataExport] = []
    for prim_name in sorted(skill.primitives.keys()):
        prim = skill.primitives[prim_name]
        prim_meta = prim.metadata  # type: ignore[attr-defined]
        primitive_exports.append(
            PrimitiveMetadataExport.from_primitive(prim_name, prim_meta)
        )

    return SkillSearchResult(
        name=skill.manifest.name,
        score=score,
        version="1.0",
        skill_metadata=skill_meta_dict,
        primitive_metadata=primitive_exports,
        skill=skill,
    )
