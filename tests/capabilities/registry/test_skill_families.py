"""
Phase 3.6.4 — Tests for skill family inference and grouping.

Validates that ``infer_skill_family`` and ``group_skills_by_family`` are
deterministic, stable, and follow the canonical family order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


# ── Fake manifest metadata (mirrors SkillManifestMetadata) ──────────────────

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
    """Minimal fake skill with manifest (carrying FakeManifestMetadata)."""
    def __init__(self, name: str, manifest_metadata: FakeManifestMetadata = None):
        self.manifest = FakeManifest(name, manifest_metadata)


def _make_manifest_meta(**overrides) -> FakeManifestMetadata:
    base = FakeManifestMetadata()
    merged = {**base.__dict__, **overrides}
    return FakeManifestMetadata(**merged)


# ═══════════════════════════════════════════════════════════════════════════
# infer_skill_family tests
# ═══════════════════════════════════════════════════════════════════════════

class TestInferSkillFamily:
    """Tests for ``infer_skill_family``."""

    # ── Name‑based prefix detection ─────────────────────────────────────

    def test_fetch_prefix(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        assert infer_skill_family(FakeSkill("fetch.http")) == "fetch"
        assert infer_skill_family(FakeSkill("fetch.filesystem")) == "fetch"

    def test_file_prefix(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        assert infer_skill_family(FakeSkill("file.read")) == "file"
        assert infer_skill_family(FakeSkill("file.write")) == "file"

    def test_parse_prefix(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        assert infer_skill_family(FakeSkill("parse.json")) == "parse"
        assert infer_skill_family(FakeSkill("parse.yaml")) == "parse"

    def test_transform_prefix(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        assert infer_skill_family(FakeSkill("transform.text")) == "transform"
        assert infer_skill_family(FakeSkill("transform.data")) == "transform"

    def test_browser_prefix(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        assert infer_skill_family(FakeSkill("browser.navigate")) == "browser"
        assert infer_skill_family(FakeSkill("browser.click")) == "browser"

    # ── Tag‑based fallback ──────────────────────────────────────────────

    def test_tag_fallback_when_no_prefix(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        meta = _make_manifest_meta(tags=["fetch"])
        skill = FakeSkill("my.custom.skill", meta)
        assert infer_skill_family(skill) == "fetch"

    def test_tag_fallback_file(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        meta = _make_manifest_meta(tags=["helper", "file"])
        skill = FakeSkill("helper.io", meta)
        assert infer_skill_family(skill) == "file"

    def test_tag_fallback_parse(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        meta = _make_manifest_meta(tags=["parse"])
        skill = FakeSkill("datatool.extract", meta)
        assert infer_skill_family(skill) == "parse"

    def test_tag_fallback_transform(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        meta = _make_manifest_meta(tags=["transform"])
        skill = FakeSkill("mapper.apply", meta)
        assert infer_skill_family(skill) == "transform"

    def test_tag_fallback_browser(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        meta = _make_manifest_meta(tags=["browser"])
        skill = FakeSkill("web.interact", meta)
        assert infer_skill_family(skill) == "browser"

    # ── Default family ──────────────────────────────────────────────────

    def test_default_family_when_no_prefix_or_tag(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        assert infer_skill_family(FakeSkill("unknown.skill")) == "generic"

    def test_default_family_when_no_metadata(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        # FakeSkill with no manifest_metadata → manifest.metadata is None
        assert infer_skill_family(FakeSkill("random.name")) == "generic"

    def test_default_family_when_empty_tags(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        meta = _make_manifest_meta(tags=["helper", "utility"])  # none are family tags
        skill = FakeSkill("helper.clean", meta)
        assert infer_skill_family(skill) == "generic"

    # ── Determinism ─────────────────────────────────────────────────────

    def test_deterministic_on_repeated_calls(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        skill = FakeSkill("fetch.data")
        results = [infer_skill_family(skill) for _ in range(10)]
        assert all(r == "fetch" for r in results)

    def test_prefix_takes_priority_over_tags(self):
        from src.capabilities.registry.skill_families import infer_skill_family

        meta = _make_manifest_meta(tags=["parse"])  # tag says parse
        skill = FakeSkill("fetch.data", meta)       # prefix says fetch
        assert infer_skill_family(skill) == "fetch"


# ═══════════════════════════════════════════════════════════════════════════
# group_skills_by_family tests
# ═══════════════════════════════════════════════════════════════════════════

class TestGroupSkillsByFamily:
    """Tests for ``group_skills_by_family``."""

    def test_all_families_present_in_canonical_order(self):
        from src.capabilities.registry.skill_families import group_skills_by_family

        skills = [
            FakeSkill("fetch.a"),
            FakeSkill("file.b"),
            FakeSkill("parse.c"),
            FakeSkill("transform.d"),
            FakeSkill("browser.e"),
            FakeSkill("generic.x"),
        ]
        groups = group_skills_by_family(skills)
        family_names = list(groups.keys())
        assert family_names == ["fetch", "file", "parse", "transform", "browser", "generic"]

    def test_skills_sorted_by_name_within_family(self):
        from src.capabilities.registry.skill_families import group_skills_by_family

        skills = [
            FakeSkill("fetch.zulu"),
            FakeSkill("fetch.alpha"),
            FakeSkill("fetch.mike"),
        ]
        groups = group_skills_by_family(skills)
        names = [s.manifest.name for s in groups["fetch"]]
        assert names == ["fetch.alpha", "fetch.mike", "fetch.zulu"]

    def test_empty_skills_returns_all_empty_lists(self):
        from src.capabilities.registry.skill_families import group_skills_by_family

        groups = group_skills_by_family([])
        for family in ["fetch", "file", "parse", "transform", "browser", "generic"]:
            assert groups[family] == []

    def test_deterministic_on_repeated_calls(self):
        from src.capabilities.registry.skill_families import group_skills_by_family

        skills = [
            FakeSkill("browser.z"),
            FakeSkill("fetch.a"),
            FakeSkill("generic.m"),
        ]
        g1 = group_skills_by_family(skills)
        g2 = group_skills_by_family(skills)

        for family in g1:
            assert [s.manifest.name for s in g1[family]] == [
                s.manifest.name for s in g2[family]
            ]

    def test_mixed_families_grouped_correctly(self):
        from src.capabilities.registry.skill_families import group_skills_by_family

        meta_fetch = _make_manifest_meta(tags=["fetch"])
        meta_parse = _make_manifest_meta(tags=["parse"])

        skills = [
            FakeSkill("fetch.http"),
            FakeSkill("tagged.fetch", meta_fetch),  # also fetch via tag
            FakeSkill("parse.json"),
            FakeSkill("tagged.parse", meta_parse),
            FakeSkill("unknown.foo"),
        ]
        groups = group_skills_by_family(skills)

        fetch_names = [s.manifest.name for s in groups["fetch"]]
        parse_names = [s.manifest.name for s in groups["parse"]]
        generic_names = [s.manifest.name for s in groups["generic"]]

        assert len(fetch_names) == 2
        assert "fetch.http" in fetch_names
        assert "tagged.fetch" in fetch_names
        assert len(parse_names) == 2
        assert "parse.json" in parse_names
        assert "tagged.parse" in parse_names
        assert generic_names == ["unknown.foo"]
