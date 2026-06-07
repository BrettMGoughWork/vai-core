"""
Phase 3.5.4 — Tests for registry rebuild stability.

Validates that rebuilding the registry from the same skills produces
identical discovery results, regardless of registration order or
presence of unrelated skills.
"""
from __future__ import annotations

import hashlib
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
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description


class FakeSkill:
    def __init__(self, name: str, metadata: FakeSkillMetadata, primitives: Dict[str, FakePrimitive],
                 description: str = ""):
        self.manifest = FakeManifest(name, description)
        self.metadata = metadata
        self.primitives = primitives


# ── rebuildable registry ──────────────────────────────────────────────────

class FakeRegistry:
    """Registry that can be built from a list of skills."""

    def __init__(self, skills: List[FakeSkill] = None):
        self._skills: Dict[str, FakeSkill] = {}
        self._order: List[str] = []
        for s in (skills or []):
            self.register(s)

    def register(self, skill: FakeSkill) -> None:
        self._skills[skill.manifest.name] = skill
        self._order.append(skill.manifest.name)

    def get(self, name: str) -> FakeSkill | None:
        return self._skills.get(name)

    def __iter__(self):
        return iter(self._skills.values())

    def __len__(self):
        return len(self._skills)


# ── canonical hash (reused from hashing tests) ────────────────────────────

def compute_hash(result) -> str:
    """Compute a stable SHA‑256 hash of a SkillSearchResult."""
    primitives = []
    for pe in result.primitive_metadata:
        pe_dict = vars(pe).copy()
        pe_dict["side_effects"] = sorted(pe_dict["side_effects"])
        pe_dict["failure_modes"] = sorted(pe_dict["failure_modes"])
        pe_dict["prerequisites"] = sorted(pe_dict["prerequisites"])
        primitives.append(pe_dict)

    sm = dict(result.skill_metadata)
    sm["side_effects"] = sorted(sm["side_effects"])
    sm["failure_modes"] = sorted(sm["failure_modes"])
    sm["prerequisites"] = sorted(sm["prerequisites"])

    canonical = json.dumps(
        {
            "name": result.name,
            "score": result.score,
            "version": result.version,
            "skill_metadata": sm,
            "primitive_metadata": primitives,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════
# Registry rebuild stability tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRegistryRebuildStability:
    """Rebuilding the registry from the same skills produces identical results."""

    def test_same_skills_same_results(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("r.prim", FakePrimitiveMetadata(cost_latency=10))
        meta = FakeSkillMetadata(cost_latency=100)
        skill = FakeSkill("rebuild-skill", meta, {"r.prim": prim})

        reg1 = FakeRegistry([skill])
        reg2 = FakeRegistry([skill])

        r1 = build_discovery_result(reg1.get("rebuild-skill"), 0.5)
        r2 = build_discovery_result(reg2.get("rebuild-skill"), 0.5)

        assert r1.name == r2.name
        assert r1.skill_metadata == r2.skill_metadata
        assert compute_hash(r1) == compute_hash(r2)

    def test_different_registration_order_same_results(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("o.prim", FakePrimitiveMetadata())
        target = FakeSkill("target", FakeSkillMetadata(), {"o.prim": prim})
        other_a = FakeSkill("alpha", FakeSkillMetadata(cost_latency=10), {})
        other_b = FakeSkill("beta", FakeSkillMetadata(cost_latency=20), {})
        other_c = FakeSkill("gamma", FakeSkillMetadata(cost_latency=30), {})

        reg1 = FakeRegistry([target, other_a, other_b, other_c])
        reg2 = FakeRegistry([other_c, other_b, other_a, target])
        reg3 = FakeRegistry([other_a, target, other_c, other_b])

        r1 = build_discovery_result(reg1.get("target"), 0.5)
        r2 = build_discovery_result(reg2.get("target"), 0.5)
        r3 = build_discovery_result(reg3.get("target"), 0.5)

        assert r1.skill_metadata == r2.skill_metadata == r3.skill_metadata
        assert compute_hash(r1) == compute_hash(r2) == compute_hash(r3)

    def test_extra_unrelated_skills_do_not_affect_target(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("t.prim", FakePrimitiveMetadata(cost_latency=42))
        target = FakeSkill("target", FakeSkillMetadata(cost_latency=420), {"t.prim": prim})

        reg_minimal = FakeRegistry([target])
        r_min = build_discovery_result(reg_minimal.get("target"), 0.5)

        unrelated = [
            FakeSkill(f"extra-{i}", FakeSkillMetadata(cost_latency=i * 100),
                      {"x.prim": FakePrimitive("x.prim", FakePrimitiveMetadata())})
            for i in range(1, 11)
        ]
        all_skills = [target] + unrelated
        reg_full = FakeRegistry(all_skills)
        r_full = build_discovery_result(reg_full.get("target"), 0.5)

        assert r_min.skill_metadata == r_full.skill_metadata
        assert compute_hash(r_min) == compute_hash(r_full)

    def test_discovery_order_stable_across_rebuilds(self):
        import math

        def fake_embedding(text: str) -> List[float]:
            seed = sum(ord(c) for c in text)
            return [
                math.sin(seed * 0.1),
                math.cos(seed * 0.1),
                math.sin(seed * 0.2),
            ]

        def cosine_similarity(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            n1 = math.sqrt(sum(x * x for x in a))
            n2 = math.sqrt(sum(y * y for y in b))
            return dot / (n1 * n2) if n1 and n2 else 0.0

        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("d.prim", FakePrimitiveMetadata())
        skills = [
            FakeSkill("one", FakeSkillMetadata(), {"d.prim": prim}, "first"),
            FakeSkill("two", FakeSkillMetadata(), {"d.prim": prim}, "second"),
            FakeSkill("three", FakeSkillMetadata(), {"d.prim": prim}, "third"),
        ]

        reg1 = FakeRegistry(skills)
        reg2 = FakeRegistry(list(reversed(skills)))

        def search_ordered(query, reg):
            qemb = fake_embedding(query)
            results = []
            for skill in reg:
                text = f"{skill.manifest.name}\n{skill.manifest.description}"
                semb = fake_embedding(text)
                score = cosine_similarity(qemb, semb)
                if score > 0:
                    results.append(build_discovery_result(skill, score))
            results.sort(key=lambda r: r.score, reverse=True)
            return results

        r1 = search_ordered("first", reg1)
        r2 = search_ordered("first", reg2)

        names1 = [r.name for r in r1]
        names2 = [r.name for r in r2]
        assert names1 == names2

    def test_hash_stable_across_entire_rebuild_cycle(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim_a = FakePrimitive("a.prim", FakePrimitiveMetadata(cost_latency=5))
        prim_b = FakePrimitive("b.prim", FakePrimitiveMetadata(cost_latency=15))
        meta = FakeSkillMetadata(cost_latency=50)

        # Build 3 registries with same skills in different orders
        reg1 = FakeRegistry([
            FakeSkill("target", meta, {"b.prim": prim_b, "a.prim": prim_a}),
            FakeSkill("extra", FakeSkillMetadata(), {"x.prim": FakePrimitive("x.prim", FakePrimitiveMetadata())}),
        ])
        reg2 = FakeRegistry([
            FakeSkill("extra", FakeSkillMetadata(), {"x.prim": FakePrimitive("x.prim", FakePrimitiveMetadata())}),
            FakeSkill("target", meta, {"a.prim": prim_a, "b.prim": prim_b}),
        ])
        # Rebuild: serialize and reconstruct
        reg3 = FakeRegistry([reg2.get("target"), reg2.get("extra")])

        r1 = build_discovery_result(reg1.get("target"), 0.5)
        r2 = build_discovery_result(reg2.get("target"), 0.5)
        r3 = build_discovery_result(reg3.get("target"), 0.5)

        h1 = compute_hash(r1)
        h2 = compute_hash(r2)
        h3 = compute_hash(r3)

        assert h1 == h2 == h3

    def test_metadata_ordering_stable_across_rebuilds(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim_a = FakePrimitive("a.prim", FakePrimitiveMetadata())
        prim_b = FakePrimitive("b.prim", FakePrimitiveMetadata())
        meta = FakeSkillMetadata()

        reg1 = FakeRegistry([
            FakeSkill("target", meta, {"a.prim": prim_a, "b.prim": prim_b}),
        ])
        reg2 = FakeRegistry([
            FakeSkill("target", meta, {"b.prim": prim_b, "a.prim": prim_a}),
        ])

        r1 = build_discovery_result(reg1.get("target"), 0.5)
        r2 = build_discovery_result(reg2.get("target"), 0.5)

        # Metadata field keys should appear in the same order
        keys1 = list(r1.skill_metadata.keys())
        keys2 = list(r2.skill_metadata.keys())
        assert keys1 == keys2

        # Primitive metadata names sorted alphabetically in hash, so hash stability passes
        assert compute_hash(r1) == compute_hash(r2)
