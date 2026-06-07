"""
Phase 3.5.2 — Tests for metadata export in semantic skill discovery.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

import pytest


# ── fake metadata dataclasses (mirror capability_metadata.py) ──────────────

@dataclass
class FakePrimitiveMetadata:
    cost_latency: int = 50
    cost_resources: str = "low"
    determinism: str = "pure"
    side_effects: List[str] = None
    output_schema: Dict[str, Any] = None
    failure_modes: List[str] = None
    safety_level: str = "low"
    prerequisites: List[str] = None

    def __post_init__(self):
        if self.side_effects is None:
            self.side_effects = []
        if self.output_schema is None:
            self.output_schema = {"type": "object"}
        if self.failure_modes is None:
            self.failure_modes = []
        if self.prerequisites is None:
            self.prerequisites = []


@dataclass
class FakeSkillMetadata:
    cost_latency: int = 200
    cost_resources: str = "medium"
    determinism: str = "impure"
    side_effects: List[str] = None
    output_schema: Dict[str, Any] = None
    failure_modes: List[str] = None
    safety_level: str = "medium"
    prerequisites: List[str] = None

    def __post_init__(self):
        if self.side_effects is None:
            self.side_effects = ["fs"]
        if self.output_schema is None:
            self.output_schema = {"type": "object", "properties": {"result": {"type": "string"}}}
        if self.failure_modes is None:
            self.failure_modes = ["FileNotFoundError"]
        if self.prerequisites is None:
            self.prerequisites = ["auth:user"]


# ── fake objects ───────────────────────────────────────────────────────────

class FakePrimitive:
    """Minimal fake primitive carrying metadata."""
    def __init__(self, name: str, metadata: FakePrimitiveMetadata):
        self.name = name
        self.metadata = metadata


class FakeManifest:
    """Minimal fake manifest."""
    def __init__(self, name: str):
        self.name = name


class FakeSkill:
    """Minimal fake skill carrying metadata and primitives."""
    def __init__(
        self,
        name: str,
        metadata: FakeSkillMetadata,
        primitives: Dict[str, FakePrimitive],
    ):
        self.manifest = FakeManifest(name)
        self.metadata = metadata
        self.primitives = primitives


# ── helper ─────────────────────────────────────────────────────────────────

def _make_primitive_meta(**overrides) -> FakePrimitiveMetadata:
    return FakePrimitiveMetadata(**{**FakePrimitiveMetadata().__dict__, **overrides})


def _make_skill_meta(**overrides) -> FakeSkillMetadata:
    return FakeSkillMetadata(**{**FakeSkillMetadata().__dict__, **overrides})


# ═══════════════════════════════════════════════════════════════════════════
# PrimitiveMetadataExport tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPrimitiveMetadataExport:
    """Tests for PrimitiveMetadataExport dataclass."""

    def test_from_primitive_copies_all_fields(self):
        from src.capabilities.registry.skill_discovery_result import PrimitiveMetadataExport

        meta = FakePrimitiveMetadata(
            cost_latency=75,
            cost_resources="medium",
            determinism="impure",
            side_effects=["fs"],
            output_schema={"type": "string"},
            failure_modes=["TimeoutError"],
            safety_level="medium",
            prerequisites=["auth:admin"],
        )
        result = PrimitiveMetadataExport.from_primitive("read.file", meta)

        assert result.name == "read.file"
        assert result.version == "1.0"
        assert result.cost_latency == 75
        assert result.cost_resources == "medium"
        assert result.determinism == "impure"
        assert result.side_effects == ["fs"]
        assert result.output_schema == {"type": "string"}
        assert result.failure_modes == ["TimeoutError"]
        assert result.safety_level == "medium"
        assert result.prerequisites == ["auth:admin"]

    def test_export_sets_version_to_1_0_always(self):
        from src.capabilities.registry.skill_discovery_result import PrimitiveMetadataExport

        result = PrimitiveMetadataExport.from_primitive("test", FakePrimitiveMetadata())
        assert result.version == "1.0"

    def test_export_is_json_serializable(self):
        from src.capabilities.registry.skill_discovery_result import PrimitiveMetadataExport

        meta = FakePrimitiveMetadata(
            side_effects=["fs", "network"],
            failure_modes=["TimeoutError", "HTTPError"],
            prerequisites=["auth:admin", "env:gpu"],
            output_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
            },
        )
        result = PrimitiveMetadataExport.from_primitive("complex.prim", meta)

        d = vars(result)
        serialized = json.dumps(d, default=str)
        deserialized = json.loads(serialized)

        assert deserialized["name"] == "complex.prim"
        assert deserialized["version"] == "1.0"
        assert isinstance(deserialized["side_effects"], list)
        assert isinstance(deserialized["failure_modes"], list)
        assert isinstance(deserialized["prerequisites"], list)
        assert isinstance(deserialized["output_schema"], dict)

    def test_different_primitive_names_produce_different_exports(self):
        from src.capabilities.registry.skill_discovery_result import PrimitiveMetadataExport

        meta = FakePrimitiveMetadata()
        a = PrimitiveMetadataExport.from_primitive("a.prim", meta)
        b = PrimitiveMetadataExport.from_primitive("b.prim", meta)

        assert a.name == "a.prim"
        assert b.name == "b.prim"
        # All other fields should be identical for same metadata
        assert a.cost_latency == b.cost_latency

    def test_side_effects_is_independent_copy(self):
        from src.capabilities.registry.skill_discovery_result import PrimitiveMetadataExport

        meta = FakePrimitiveMetadata(side_effects=["fs"])
        result = PrimitiveMetadataExport.from_primitive("test", meta)

        result.side_effects.append("network")
        assert meta.side_effects == ["fs"]


# ═══════════════════════════════════════════════════════════════════════════
# SkillDiscoveryResult tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSkillDiscoveryResult:
    """Tests for SkillDiscoveryResult dataclass."""

    def test_constructed_with_all_fields(self):
        from src.capabilities.registry.skill_discovery_result import (
            SkillDiscoveryResult,
            PrimitiveMetadataExport,
        )

        skill = FakeSkill("test-skill", FakeSkillMetadata(), {})
        result = SkillDiscoveryResult(
            name="test-skill",
            score=0.85,
            version="1.0",
            skill_metadata={"version": "1.0"},
            primitive_metadata=[],
            skill=skill,
        )

        assert result.name == "test-skill"
        assert result.score == 0.85
        assert result.version == "1.0"
        assert result.skill_metadata == {"version": "1.0"}
        assert result.primitive_metadata == []
        assert result.skill is skill

    def test_skill_field_not_in_repr(self):
        from src.capabilities.registry.skill_discovery_result import SkillDiscoveryResult

        skill = FakeSkill("test", FakeSkillMetadata(), {})
        result = SkillDiscoveryResult(
            name="test", score=1.0, version="1.0",
            skill_metadata={}, primitive_metadata=[], skill=skill,
        )
        r = repr(result)
        assert "skill=" not in r

    def test_version_always_1_0(self):
        from src.capabilities.registry.skill_discovery_result import SkillDiscoveryResult

        result = SkillDiscoveryResult(
            name="test", score=1.0, version="1.0",
            skill_metadata={}, primitive_metadata=[], skill=None,
        )
        assert result.version == "1.0"


# ═══════════════════════════════════════════════════════════════════════════
# build_discovery_result tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildDiscoveryResult:
    """Tests for build_discovery_result function."""

    def test_result_name_matches_skill_manifest_name(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        skill = FakeSkill("my-skill", FakeSkillMetadata(), {})
        result = build_discovery_result(skill, 0.95)

        assert result.name == "my-skill"

    def test_result_score_matches_input(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        skill = FakeSkill("s", FakeSkillMetadata(), {})
        result = build_discovery_result(skill, 0.72)

        assert result.score == 0.72

    def test_version_is_1_0(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        skill = FakeSkill("s", FakeSkillMetadata(), {})
        result = build_discovery_result(skill, 1.0)

        assert result.version == "1.0"

    def test_skill_metadata_includes_all_fields(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        meta = FakeSkillMetadata(
            cost_latency=300,
            cost_resources="high",
            determinism="nondeterministic",
            side_effects=["network", "dangerous"],
            output_schema={"type": "object", "properties": {"x": {"type": "number"}}},
            failure_modes=["HTTPError", "TimeoutError"],
            safety_level="high",
            prerequisites=["auth:admin"],
        )
        skill = FakeSkill("rich-skill", meta, {})
        result = build_discovery_result(skill, 0.5)

        sm = result.skill_metadata
        assert sm["version"] == "1.0"
        assert sm["cost_latency"] == 300
        assert sm["cost_resources"] == "high"
        assert sm["determinism"] == "nondeterministic"
        assert sm["side_effects"] == ["network", "dangerous"]
        assert sm["output_schema"] == {"type": "object", "properties": {"x": {"type": "number"}}}
        assert sm["failure_modes"] == ["HTTPError", "TimeoutError"]
        assert sm["safety_level"] == "high"
        assert sm["prerequisites"] == ["auth:admin"]

    def test_skill_metadata_version_inserted(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        # SkillMetadata dataclass does NOT have a version field
        skill = FakeSkill("vcheck", FakeSkillMetadata(), {})
        result = build_discovery_result(skill, 1.0)

        assert result.skill_metadata["version"] == "1.0"

    def test_primitive_metadata_populated_for_each_primitive(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim_a = FakePrimitive("read.file", FakePrimitiveMetadata(cost_latency=10))
        prim_b = FakePrimitive("write.file", FakePrimitiveMetadata(cost_latency=20))
        skill = FakeSkill("io-skill", FakeSkillMetadata(), {"read.file": prim_a, "write.file": prim_b})
        result = build_discovery_result(skill, 0.9)

        assert len(result.primitive_metadata) == 2
        names = [p.name for p in result.primitive_metadata]
        assert "read.file" in names
        assert "write.file" in names

    def test_empty_primitives_produces_empty_list(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        skill = FakeSkill("no-prims", FakeSkillMetadata(), {})
        result = build_discovery_result(skill, 0.0)

        assert result.primitive_metadata == []

    def test_primitive_export_has_version_1_0(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("only.prim", FakePrimitiveMetadata())
        skill = FakeSkill("single", FakeSkillMetadata(), {"only.prim": prim})
        result = build_discovery_result(skill, 0.8)

        for pe in result.primitive_metadata:
            assert pe.version == "1.0"

    def test_skill_reference_preserved_in_result(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        skill = FakeSkill("ref-test", FakeSkillMetadata(), {})
        result = build_discovery_result(skill, 0.5)

        assert result.skill is skill

    def test_deterministic_output_for_same_input(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("det.prim", FakePrimitiveMetadata())
        meta = FakeSkillMetadata()
        skill_a = FakeSkill("det-skill", meta, {"det.prim": prim})
        skill_b = FakeSkill("det-skill", meta, {"det.prim": prim})

        result_a = build_discovery_result(skill_a, 0.6)
        result_b = build_discovery_result(skill_b, 0.6)

        assert result_a.name == result_b.name
        assert result_a.score == result_b.score
        assert result_a.version == result_b.version
        assert result_a.skill_metadata == result_b.skill_metadata
        assert len(result_a.primitive_metadata) == len(result_b.primitive_metadata)

    def test_score_zero_still_produces_valid_result(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        skill = FakeSkill("zero-score", FakeSkillMetadata(), {})
        result = build_discovery_result(skill, 0.0)

        assert result.score == 0.0
        assert result.name == "zero-score"

    def test_primitive_metadata_fields_match_source_primitive(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        pmeta = FakePrimitiveMetadata(
            cost_latency=99,
            cost_resources="high",
            determinism="nondeterministic",
            side_effects=["network", "dangerous"],
            output_schema={"type": "array"},
            failure_modes=["RuntimeError", "TimeoutError"],
            safety_level="high",
            prerequisites=["auth:root", "env:gpu"],
        )
        prim = FakePrimitive("risky.prim", pmeta)
        skill = FakeSkill("risky-skill", FakeSkillMetadata(), {"risky.prim": prim})
        result = build_discovery_result(skill, 0.3)

        pe = result.primitive_metadata[0]
        assert pe.cost_latency == 99
        assert pe.cost_resources == "high"
        assert pe.determinism == "nondeterministic"
        assert pe.side_effects == ["network", "dangerous"]
        assert pe.output_schema == {"type": "array"}
        assert pe.failure_modes == ["RuntimeError", "TimeoutError"]
        assert pe.safety_level == "high"
        assert pe.prerequisites == ["auth:root", "env:gpu"]

    def test_skill_metadata_is_deep_copy_of_source(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        meta = FakeSkillMetadata(side_effects=["fs"])
        skill = FakeSkill("copy-test", meta, {})
        result = build_discovery_result(skill, 0.5)

        result.skill_metadata["side_effects"].append("network")
        assert meta.side_effects == ["fs"]


# ═══════════════════════════════════════════════════════════════════════════
# JSON serialization integration tests
# ═══════════════════════════════════════════════════════════════════════════

class TestMetadataExportSerialization:
    """Ensures metadata export results are JSON‑serializable."""

    def test_full_discovery_result_serializable(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim_a = FakePrimitive("a.prim", FakePrimitiveMetadata())
        prim_b = FakePrimitive("b.prim", FakePrimitiveMetadata(cost_latency=100))
        meta = FakeSkillMetadata()
        skill = FakeSkill("serial-test", meta, {"a.prim": prim_a, "b.prim": prim_b})
        result = build_discovery_result(skill, 0.77)

        serializable = {
            "name": result.name,
            "score": result.score,
            "version": result.version,
            "skill_metadata": result.skill_metadata,
            "primitive_metadata": [
                {
                    "name": pe.name,
                    "version": pe.version,
                    "cost_latency": pe.cost_latency,
                    "cost_resources": pe.cost_resources,
                    "determinism": pe.determinism,
                    "side_effects": pe.side_effects,
                    "output_schema": pe.output_schema,
                    "failure_modes": pe.failure_modes,
                    "safety_level": pe.safety_level,
                    "prerequisites": pe.prerequisites,
                }
                for pe in result.primitive_metadata
            ],
        }

        dumped = json.dumps(serializable)
        loaded = json.loads(dumped)

        assert loaded["name"] == "serial-test"
        assert loaded["score"] == 0.77
        assert loaded["version"] == "1.0"
        assert len(loaded["primitive_metadata"]) == 2
