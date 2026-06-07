"""
Phase 3.6.1 — Skill manifest metadata dataclass.

SkillManifestMetadata adds structured metadata (tags, I/O types,
side-effects, safety, cost, determinism, prerequisites) to every
skill manifest.  Metadata is validated before attachment.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from src.capabilities.skills.manifest import SkillManifest


# ── Allowed enumerations ────────────────────────────────────────────

_ALLOWED_DETERMINISM = {"pure", "impure", "nondeterministic"}
_ALLOWED_SAFETY = {"low", "medium", "high"}


# ── Dataclass ───────────────────────────────────────────────────────

@dataclass
class SkillManifestMetadata:
    """Structured metadata attached to every skill manifest.

    All fields required.  Raise ValueError on structural mismatch.
    """

    tags: List[str]
    input_types: Dict[str, str]
    output_types: Dict[str, str]
    side_effects: List[str]
    safety_level: str
    cost_estimate: Dict[str, Any]
    determinism: str
    prerequisites: List[str]

    def validate(self) -> None:
        """Validate all fields — raises ValueError on any mismatch."""
        _validate_manifest_metadata(self)


# ── Validation ──────────────────────────────────────────────────────

def _validate_manifest_metadata(m: SkillManifestMetadata) -> None:
    # ── lists of str ──
    for name, attr in [
        ("tags", m.tags),
        ("side_effects", m.side_effects),
        ("prerequisites", m.prerequisites),
    ]:
        if not isinstance(attr, list) or not all(isinstance(x, str) for x in attr):
            raise ValueError(f"{name} must be a list of str")

    # ── dict[str, str] ──
    for name, attr in [("input_types", m.input_types), ("output_types", m.output_types)]:
        if not isinstance(attr, dict):
            raise ValueError(f"{name} must be a dict")
        for k, v in attr.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError(f"all keys and values in {name} must be str")

    # ── cost_estimate ──
    ce = m.cost_estimate
    if not isinstance(ce, dict):
        raise ValueError("cost_estimate must be a dict")
    if not isinstance(ce.get("latency"), int):
        raise ValueError('cost_estimate["latency"] must be an int')
    if not isinstance(ce.get("resources"), str):
        raise ValueError('cost_estimate["resources"] must be a str')

    # ── enumerations ──
    if m.determinism not in _ALLOWED_DETERMINISM:
        raise ValueError(
            f"determinism must be one of {sorted(_ALLOWED_DETERMINISM)}, "
            f"got {m.determinism!r}"
        )
    if m.safety_level not in _ALLOWED_SAFETY:
        raise ValueError(
            f"safety_level must be one of {sorted(_ALLOWED_SAFETY)}, "
            f"got {m.safety_level!r}"
        )


# ── Attachment ──────────────────────────────────────────────────────

def attach_metadata_to_manifest(
    manifest: SkillManifest,
    metadata: SkillManifestMetadata,
) -> None:
    """Attach validated metadata to a ``SkillManifest``.

    Args:
        manifest: Target manifest (mutated in-place).
        metadata: Validated ``SkillManifestMetadata`` instance.

    Raises:
        ValueError: If *metadata* fails validation.
    """
    metadata.validate()
    manifest.metadata = metadata  # type: ignore[attr-defined]
