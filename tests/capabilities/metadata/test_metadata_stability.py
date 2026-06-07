"""
Phase 3.5.4 — Tests for metadata stability across repeated calls.

Validates that metadata is stable: same skill → identical output,
same query → identical ordering, stability with unrelated skills.
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
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description


class FakeSkill:
    def __init__(self, name: str, metadata: FakeSkillMetadata, primitives: Dict[str, FakePrimitive],
                 description: str = ""):
        self.manifest = FakeManifest(name, description)
        self.metadata = metadata
        self.primitives = primitives


# ── fake registry (minimal) ────────────────────────────────────────────────

class FakeRegistry:
    """Minimal fake registry storing skills indexed by manifest name."""
    def __init__(self, skills: List[FakeSkill] = None):
        self._skills: Dict[str, FakeSkill] = {}
        for s in (skills or []):
            self._skills[s.manifest.name] = s

    def register(self, skill: FakeSkill) -> None:
        self._skills[skill.manifest.name] = skill

    def get(self, name: str) -> FakeSkill | None:
        return self._skills.get(name)

    def list(self, filter_fn=None):
        skills = list(self._skills.values())
        if filter_fn is not None:
            skills = [s for s in skills if filter_fn(s)]
        return skills

    def __iter__(self):
        return iter(self._skills.values())

    def __len__(self):
        return len(self._skills)


# ═══════════════════════════════════════════════════════════════════════════
# Stability tests via build_discovery_result
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildDiscoveryResultStability:
    """build_discovery_result is fully stable for same input."""

    def test_repeated_calls_produce_identical_output(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("stable.prim", FakePrimitiveMetadata())
        meta = FakeSkillMetadata()
        skill = FakeSkill("stable-skill", meta, {"stable.prim": prim})

        results = [build_discovery_result(skill, 0.75) for _ in range(5)]

        ref = results[0]
        for r in results[1:]:
            assert r.name == ref.name
            assert r.score == ref.score
            assert r.version == ref.version
            assert r.skill_metadata == ref.skill_metadata
            for a, b in zip(r.primitive_metadata, ref.primitive_metadata):
                assert vars(a) == vars(b)

    def test_different_score_does_not_change_metadata(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        skill = FakeSkill("score-test", FakeSkillMetadata(), {})
        r1 = build_discovery_result(skill, 0.2)
        r2 = build_discovery_result(skill, 0.9)

        assert r1.skill_metadata == r2.skill_metadata
        assert r1.primitive_metadata == r2.primitive_metadata

    def test_metadata_stable_when_other_skills_present(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        target_prim = FakePrimitive("t.prim", FakePrimitiveMetadata(cost_latency=10))
        target_meta = FakeSkillMetadata(cost_latency=100)
        target = FakeSkill("target", target_meta, {"t.prim": target_prim})

        other_prim = FakePrimitive("o.prim", FakePrimitiveMetadata(cost_latency=999))
        other_meta = FakeSkillMetadata(cost_latency=9999)
        other = FakeSkill("other", other_meta, {"o.prim": other_prim})

        # Build registry with both
        reg = FakeRegistry([target, other])

        r1 = build_discovery_result(target, 0.5)
        r2 = build_discovery_result(reg.get("target"), 0.5)

        assert r1.skill_metadata == r2.skill_metadata
        assert len(r1.primitive_metadata) == 1
        assert r1.primitive_metadata[0].name == "t.prim"


class TestSearchResultStability:
    """Semantic search results are stable for same query."""

    def test_same_query_same_ranking(self):
        import math

        def fake_embedding(text: str) -> List[float]:
            # Deterministic fake: hash characters to produce a vector
            seed = sum(ord(c) for c in text)
            return [
                math.sin(seed * 0.1),
                math.cos(seed * 0.1),
                math.sin(seed * 0.2),
            ]

        from src.capabilities.registry.skill_discovery_result import (
            build_discovery_result,
            SkillDiscoveryResult,
        )

        def cosine_similarity(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            n1 = math.sqrt(sum(x * x for x in a))
            n2 = math.sqrt(sum(y * y for y in b))
            return dot / (n1 * n2) if n1 and n2 else 0.0

        def search(query: str, registry: FakeRegistry) -> List[SkillDiscoveryResult]:
            qemb = fake_embedding(query)
            results = []
            for skill in registry:
                text = f"{skill.manifest.name}\n{skill.manifest.description}"
                semb = fake_embedding(text)
                score = cosine_similarity(qemb, semb)
                if score > 0:
                    results.append(build_discovery_result(skill, score))
            results.sort(key=lambda r: r.score, reverse=True)
            return results

        prim = FakePrimitive("srch.prim", FakePrimitiveMetadata())
        reg = FakeRegistry([
            FakeSkill("alpha", FakeSkillMetadata(cost_latency=200), {"srch.prim": prim}, "first skill"),
            FakeSkill("beta", FakeSkillMetadata(cost_latency=100), {"srch.prim": prim}, "second skill"),
        ])

        r1 = search("first", reg)
        r2 = search("first", reg)

        assert [s.name for s in r1] == [s.name for s in r2]
        assert [s.score for s in r1] == [s.score for s in r2]

    def test_search_results_contain_stable_metadata(self):
        import math

        def fake_embedding(text: str) -> List[float]:
            seed = sum(ord(c) for c in text)
            return [math.sin(seed * 0.1), math.cos(seed * 0.1)]

        def cosine_similarity(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            n1 = math.sqrt(sum(x * x for x in a))
            n2 = math.sqrt(sum(y * y for y in b))
            return dot / (n1 * n2) if n1 and n2 else 0.0

        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("m.prim", FakePrimitiveMetadata())
        meta = FakeSkillMetadata()
        skill = FakeSkill("meta-stable", meta, {"m.prim": prim})
        reg = FakeRegistry([skill])

        def search_one(query, reg):
            qemb = fake_embedding(query)
            best_score = 0
            best_skill = None
            for s in reg:
                semb = fake_embedding(s.manifest.name)
                score = cosine_similarity(qemb, semb)
                if score > best_score:
                    best_score = score
                    best_skill = s
            return build_discovery_result(best_skill, best_score) if best_skill else None

        r1 = search_one("meta-stable", reg)
        r2 = search_one("meta-stable", reg)

        assert r1 is not None
        assert r2 is not None
        assert r1.skill_metadata == r2.skill_metadata
        assert len(r1.primitive_metadata) == len(r2.primitive_metadata)
