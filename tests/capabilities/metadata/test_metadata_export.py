"""
Phase 3.5.4 — Tests for metadata export determinism.

Validates that SkillSearchResult exports are deterministic,
JSON‑serializable, and contain no dynamic fields.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List


# ── fake metadata dataclasses ──────────────────────────────────────────────

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
    def __init__(self, name: str, metadata: FakePrimitiveMetadata):
        self.name = name
        self.metadata = metadata


class FakeManifest:
    def __init__(self, name: str):
        self.name = name


class FakeSkill:
    def __init__(self, name: str, metadata: FakeSkillMetadata, primitives: Dict[str, FakePrimitive]):
        self.manifest = FakeManifest(name)
        self.metadata = metadata
        self.primitives = primitives


# ═══════════════════════════════════════════════════════════════════════════
# Export determinism tests
# ═══════════════════════════════════════════════════════════════════════════

class TestExportDeterminism:
    """build_discovery_result produces deterministic output."""

    def test_version_is_always_1_0(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        skill = FakeSkill("ver-skill", FakeSkillMetadata(), {})
        result = build_discovery_result(skill, 0.8)

        assert result.version == "1.0"
        assert result.skill_metadata["version"] == "1.0"

    def test_same_input_produces_identical_output(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("a.prim", FakePrimitiveMetadata())
        meta = FakeSkillMetadata()
        skill_a = FakeSkill("id-skill", meta, {"a.prim": prim})
        skill_b = FakeSkill("id-skill", meta, {"a.prim": prim})

        r1 = build_discovery_result(skill_a, 0.5)
        r2 = build_discovery_result(skill_b, 0.5)

        assert r1.name == r2.name
        assert r1.score == r2.score
        assert r1.version == r2.version
        assert r1.skill_metadata == r2.skill_metadata
        assert len(r1.primitive_metadata) == len(r2.primitive_metadata)
        for a, b in zip(r1.primitive_metadata, r2.primitive_metadata):
            assert vars(a) == vars(b)

    def test_primitive_metadata_order_is_deterministic(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prims = {
            "b.prim": FakePrimitive("b.prim", FakePrimitiveMetadata()),
            "a.prim": FakePrimitive("a.prim", FakePrimitiveMetadata()),
            "c.prim": FakePrimitive("c.prim", FakePrimitiveMetadata()),
        }
        skill_a = FakeSkill("order-test", FakeSkillMetadata(), dict(prims))
        skill_b = FakeSkill("order-test", FakeSkillMetadata(), dict(prims))

        r1 = build_discovery_result(skill_a, 0.5)
        r2 = build_discovery_result(skill_b, 0.5)

        names1 = [p.name for p in r1.primitive_metadata]
        names2 = [p.name for p in r2.primitive_metadata]
        assert names1 == names2

    def test_skill_metadata_keys_are_stable(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        skill = FakeSkill("keys-test", FakeSkillMetadata(), {})
        result = build_discovery_result(skill, 1.0)

        expected_keys = {
            "version", "cost_latency", "cost_resources", "determinism",
            "side_effects", "output_schema", "failure_modes",
            "safety_level", "prerequisites",
        }
        assert set(result.skill_metadata.keys()) == expected_keys


class TestExportSerialization:
    """Exported metadata is fully JSON‑serializable."""

    def test_skill_metadata_dict_is_serializable(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        meta = FakeSkillMetadata(
            side_effects=["fs", "network"],
            output_schema={"type": "object", "properties": {"x": {"type": "number"}}},
            failure_modes=["TimeoutError"],
            prerequisites=["auth:admin"],
        )
        skill = FakeSkill("serial-skill", meta, {})
        result = build_discovery_result(skill, 0.7)

        dumped = json.dumps(result.skill_metadata)
        loaded = json.loads(dumped)
        assert loaded["version"] == "1.0"
        assert loaded["side_effects"] == ["fs", "network"]

    def test_primitive_metadata_list_is_serializable(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("ser.prim", FakePrimitiveMetadata(
            side_effects=["network"],
            failure_modes=["HTTPError"],
        ))
        skill = FakeSkill("prim-serial", FakeSkillMetadata(), {"ser.prim": prim})
        result = build_discovery_result(skill, 0.9)

        for pe in result.primitive_metadata:
            dumped = json.dumps(vars(pe), default=str)
            loaded = json.loads(dumped)
            assert loaded["name"] == "ser.prim"

    def test_full_discovery_result_dict_is_serializable(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim_a = FakePrimitive("a.prim", FakePrimitiveMetadata())
        prim_b = FakePrimitive("b.prim", FakePrimitiveMetadata())
        skill = FakeSkill("full-serial", FakeSkillMetadata(), {"a.prim": prim_a, "b.prim": prim_b})
        result = build_discovery_result(skill, 0.6)

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
        assert loaded["name"] == "full-serial"
        assert loaded["score"] == 0.6
        assert len(loaded["primitive_metadata"]) == 2


class TestNoDynamicFields:
    """Exported metadata contains no dynamic fields (timestamps, random IDs)."""

    def test_no_timestamp_field_in_skill_metadata(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        skill = FakeSkill("no-ts", FakeSkillMetadata(), {})
        result = build_discovery_result(skill, 0.5)

        for key in result.skill_metadata:
            assert "time" not in key.lower()

    def test_no_uuid_or_id_field(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        skill = FakeSkill("no-id", FakeSkillMetadata(), {})
        result = build_discovery_result(skill, 0.5)

        for key in result.skill_metadata:
            assert "uuid" not in key.lower()
            assert key != "id"

    def test_no_dynamic_field_in_primitive_export(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("static.prim", FakePrimitiveMetadata())
        skill = FakeSkill("static-skill", FakeSkillMetadata(), {"static.prim": prim})
        result = build_discovery_result(skill, 0.5)

        pe = result.primitive_metadata[0]
        pe_dict = vars(pe)
        for key in pe_dict:
            assert "time" not in key.lower()
            assert "uuid" not in key.lower()
            assert "random" not in key.lower()

    def test_no_timestamp_field_in_result_top_level(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        skill = FakeSkill("top-static", FakeSkillMetadata(), {})
        result = build_discovery_result(skill, 0.5)

        top = vars(result)
        for key in top:
            assert "time" not in key.lower()
            assert "timestamp" not in key.lower()
