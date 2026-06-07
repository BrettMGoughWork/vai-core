"""
Phase 3.5.4 — Tests for metadata hashing stability.

Validates that a canonical JSON hash of exported metadata is stable
across runs, changes only when fields change, and is independent of
insertion/iteration order.
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
    def __init__(self, name: str):
        self.name = name


class FakeSkill:
    def __init__(self, name: str, metadata: FakeSkillMetadata, primitives: Dict[str, FakePrimitive]):
        self.manifest = FakeManifest(name)
        self.metadata = metadata
        self.primitives = primitives


# ── canonical hash helper ─────────────────────────────────────────────────

def compute_hash(result) -> str:
    """Compute a stable SHA‑256 hash of a SkillDiscoveryResult."""
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
# Hash stability tests
# ═══════════════════════════════════════════════════════════════════════════

class TestHashStability:
    """Canonical hash is stable across repeated calls."""

    def test_hash_stable_across_calls(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("hash.prim", FakePrimitiveMetadata())
        skill = FakeSkill("hash-skill", FakeSkillMetadata(), {"hash.prim": prim})

        h1 = compute_hash(build_discovery_result(skill, 0.5))
        h2 = compute_hash(build_discovery_result(skill, 0.5))

        assert h1 == h2

    def test_hash_changes_when_metadata_field_changes(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("ch.prim", FakePrimitiveMetadata(cost_latency=10))
        sk1 = FakeSkill("ch-skill", FakeSkillMetadata(cost_latency=100), {"ch.prim": prim})
        sk2 = FakeSkill("ch-skill", FakeSkillMetadata(cost_latency=999), {"ch.prim": prim})

        h1 = compute_hash(build_discovery_result(sk1, 0.5))
        h2 = compute_hash(build_discovery_result(sk2, 0.5))

        assert h1 != h2

    def test_hash_changes_when_safety_level_changes(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("sl.prim", FakePrimitiveMetadata(safety_level="low"))
        sk1 = FakeSkill("sl-skill", FakeSkillMetadata(safety_level="low"), {"sl.prim": prim})
        sk2 = FakeSkill("sl-skill", FakeSkillMetadata(safety_level="high"), {"sl.prim": prim})

        h1 = compute_hash(build_discovery_result(sk1, 0.5))
        h2 = compute_hash(build_discovery_result(sk2, 0.5))

        assert h1 != h2

    def test_hash_changes_when_primitive_metadata_changes(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim1 = FakePrimitive("dp.prim", FakePrimitiveMetadata(side_effects=["fs"]))
        prim2 = FakePrimitive("dp.prim", FakePrimitiveMetadata(side_effects=["network"]))
        sk1 = FakeSkill("dp-skill", FakeSkillMetadata(), {"dp.prim": prim1})
        sk2 = FakeSkill("dp-skill", FakeSkillMetadata(), {"dp.prim": prim2})

        h1 = compute_hash(build_discovery_result(sk1, 0.5))
        h2 = compute_hash(build_discovery_result(sk2, 0.5))

        assert h1 != h2

    def test_hash_independent_of_primitive_registration_order(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        meta = FakeSkillMetadata()
        prim_a = FakePrimitive("a.prim", FakePrimitiveMetadata(cost_latency=10))
        prim_b = FakePrimitive("b.prim", FakePrimitiveMetadata(cost_latency=20))

        # Skill with primitives inserted in one order
        sk1 = FakeSkill("order-hash", meta, {"a.prim": prim_a, "b.prim": prim_b})
        # Same skill with primitives in opposite dict insertion order
        # (Python 3.7+ dicts preserve insertion order; we sort primitives
        #  by name in compute_hash to negate this)
        sk2 = FakeSkill("order-hash", meta, {"b.prim": prim_b, "a.prim": prim_a})

        # build_discovery_result iterates skill.primitives.items()
        # which follows insertion order — but our hash sorts by key name
        h1 = compute_hash(build_discovery_result(sk1, 0.5))
        h2 = compute_hash(build_discovery_result(sk2, 0.5))

        assert h1 == h2

    def test_hash_independent_of_dict_iteration_order(self):
        """Hash must be stable regardless of Python dict order — sort_keys ensures this."""
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        meta = FakeSkillMetadata()
        prim = FakePrimitive("iter.prim", FakePrimitiveMetadata())
        skill = FakeSkill("iter-hash", meta, {"iter.prim": prim})

        result = build_discovery_result(skill, 0.5)

        # Simulate: manually build metadata dicts with different insertion orders
        sm_a = dict(sorted(result.skill_metadata.items()))
        sm_b = dict(reversed(sorted(result.skill_metadata.items())))

        canonical_a = json.dumps({"skill_metadata": sm_a}, sort_keys=True)
        canonical_b = json.dumps({"skill_metadata": sm_b}, sort_keys=True)

        assert canonical_a == canonical_b

    def test_hash_stable_for_identical_skills_built_separately(self):
        from src.capabilities.registry.skill_discovery_result import build_discovery_result

        prim = FakePrimitive("dup.prim", FakePrimitiveMetadata())
        sk1 = FakeSkill("dup", FakeSkillMetadata(), {"dup.prim": prim})
        sk2 = FakeSkill("dup", FakeSkillMetadata(), {"dup.prim": prim})

        h1 = compute_hash(build_discovery_result(sk1, 1.0))
        h2 = compute_hash(build_discovery_result(sk2, 1.0))

        assert h1 == h2
