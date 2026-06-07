"""
Phase 3.6.4 — Tests for family attachment to discovery results.

Validates that ``attach_family_to_discovery_result`` correctly sets
``result.family``, is deterministic, and does not mutate other fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


# ── Fake manifest metadata ──────────────────────────────────────────────────

@dataclass
class FakeManifestMetadata:
    """Fake manifest‑level metadata with tags."""
    tags: List[str] = None
    input_types: Dict[str, str] = None
    output_types: Dict[str, str] = None
    side_effects: List[str] = None
    safety_level: str = "low"
    cost_estimate: Dict = None
    determinism: str = "pure"
    prerequisites: List[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.input_types is None:
            self.input_types = {}
        if self.output_types is None:
            self.output_types = {}
        if self.side_effects is None:
            self.side_effects = []
        if self.cost_estimate is None:
            self.cost_estimate = {"latency": 50, "resources": "low"}
        if self.prerequisites is None:
            self.prerequisites = []


# ── Fake objects ────────────────────────────────────────────────────────────

class FakeManifest:
    """Minimal fake manifest carrying name + optional metadata."""
    def __init__(self, name: str, metadata: FakeManifestMetadata = None):
        self.name = name
        self.metadata = metadata


class FakeSkill:
    """Minimal fake skill with manifest."""
    def __init__(self, name: str, manifest_metadata: FakeManifestMetadata = None):
        self.manifest = FakeManifest(name, manifest_metadata)


def _make_manifest_meta(**overrides) -> FakeManifestMetadata:
    base = FakeManifestMetadata()
    merged = {**base.__dict__, **overrides}
    return FakeManifestMetadata(**merged)


def _make_result(
    name: str,
    score: float = 0.5,
    manifest_meta: FakeManifestMetadata = None,
) -> "SkillSearchResult":
    from src.capabilities.registry.skill_discovery_result import SkillSearchResult

    skill = FakeSkill(name, manifest_meta)
    return SkillSearchResult(
        name=name,
        score=score,
        version="1.0",
        skill_metadata={},
        primitive_metadata=[],
        skill=skill,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Family attachment tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFamilyAttachment:
    """Tests for ``attach_family_to_discovery_result``."""

    def test_sets_family_correctly_for_prefix_based(self):
        from src.capabilities.registry.skill_families import (
            attach_family_to_discovery_result,
        )

        result = _make_result("fetch.http")
        attach_family_to_discovery_result(result)
        assert result.family == "fetch"

    def test_sets_family_correctly_for_tag_based(self):
        from src.capabilities.registry.skill_families import (
            attach_family_to_discovery_result,
        )

        meta = _make_manifest_meta(tags=["browser"])
        result = _make_result("web.navigate", manifest_meta=meta)
        attach_family_to_discovery_result(result)
        assert result.family == "browser"

    def test_sets_family_correctly_for_generic_fallback(self):
        from src.capabilities.registry.skill_families import (
            attach_family_to_discovery_result,
        )

        result = _make_result("random.unknown")
        attach_family_to_discovery_result(result)
        assert result.family == "generic"

    def test_deterministic_across_repeated_calls(self):
        from src.capabilities.registry.skill_families import (
            attach_family_to_discovery_result,
        )

        meta = _make_manifest_meta(tags=["parse", "transform"])
        result = _make_result("datatool.extract", manifest_meta=meta)
        attach_family_to_discovery_result(result)
        family1 = result.family

        # Repeat
        result2 = _make_result("datatool.extract", manifest_meta=meta)
        attach_family_to_discovery_result(result2)
        assert result2.family == family1

    def test_does_not_mutate_other_fields(self):
        from src.capabilities.registry.skill_families import (
            attach_family_to_discovery_result,
        )

        result = _make_result("parse.json", score=0.87)
        original_name = result.name
        original_score = result.score
        original_version = result.version
        original_skill_metadata = result.skill_metadata
        original_primitive_metadata = result.primitive_metadata
        original_skill = result.skill

        attach_family_to_discovery_result(result)

        assert result.name == original_name
        assert result.score == original_score
        assert result.version == original_version
        assert result.skill_metadata is original_skill_metadata
        assert result.primitive_metadata is original_primitive_metadata
        assert result.skill is original_skill

    def test_stable_across_registry_rebuilds(self):
        from src.capabilities.registry.skill_families import (
            attach_family_to_discovery_result,
        )

        meta = _make_manifest_meta(tags=["file"])
        result_a = _make_result("file.read", manifest_meta=meta)
        result_b = _make_result("file.read", manifest_meta=meta)

        attach_family_to_discovery_result(result_a)
        attach_family_to_discovery_result(result_b)

        assert result_a.family == result_b.family == "file"

    def test_all_prefix_families_attached_correctly(self):
        from src.capabilities.registry.skill_families import (
            attach_family_to_discovery_result,
        )

        families = {
            "fetch.http": "fetch",
            "file.read": "file",
            "parse.json": "parse",
            "transform.text": "transform",
            "browser.navigate": "browser",
        }

        for name, expected_family in families.items():
            result = _make_result(name)
            attach_family_to_discovery_result(result)
            assert result.family == expected_family, f"{name} → {result.family}, expected {expected_family}"
