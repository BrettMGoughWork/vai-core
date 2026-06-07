"""
Phase 3.6.4 — Tests for deterministic skill ranking.

Validates that ``rank_discovered_skills``, ``compute_schema_compatibility``,
and ``extract_query_tag`` are fully deterministic and respect the strict
priority pipeline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest


# ── Fake manifest metadata (mirrors SkillManifestMetadata) ──────────────────

@dataclass
class FakeManifestMetadata:
    """Fake manifest‑level metadata with tags, I/O types, safety, etc."""
    tags: List[str] = None
    input_types: Dict[str, str] = None
    output_types: Dict[str, str] = None
    side_effects: List[str] = None
    safety_level: str = "low"
    cost_estimate: Dict[str, Any] = None
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
    """Minimal fake manifest carrying name + manifest‑level metadata."""
    def __init__(self, name: str, metadata: FakeManifestMetadata = None):
        self.name = name
        self.metadata = metadata  # SkillManifestMetadata equivalent


class FakeSkill:
    """Minimal fake skill with manifest (carrying FakeManifestMetadata)."""
    def __init__(
        self,
        name: str,
        manifest_metadata: FakeManifestMetadata = None,
    ):
        self.manifest = FakeManifest(name, manifest_metadata)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_manifest_meta(**overrides) -> FakeManifestMetadata:
    defaults = FakeManifestMetadata().__dict__.copy()
    defaults.pop("tags")
    defaults.pop("input_types")
    defaults.pop("output_types")
    defaults.pop("side_effects")
    defaults.pop("cost_estimate")
    defaults.pop("prerequisites")
    # Re‑build with correct defaults for nested fields
    base = FakeManifestMetadata()
    merged = {**base.__dict__, **overrides}
    return FakeManifestMetadata(**merged)


def _make_result(
    name: str,
    score: float,
    manifest_meta: FakeManifestMetadata = None,
) -> "SkillSearchResult":
    """Build a ``SkillSearchResult`` with a controlled fake skill."""
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
# rank_discovered_skills tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRankDiscoveredSkills:
    """Tests for ``rank_discovered_skills``."""

    def test_same_query_repeated_yields_identical_order(self):
        from src.capabilities.registry.deterministic_ranking import (
            rank_discovered_skills,
        )

        meta_a = _make_manifest_meta(tags=["fetch"], safety_level="low", determinism="pure")
        meta_b = _make_manifest_meta(tags=["parse"], safety_level="medium", determinism="impure")
        meta_c = _make_manifest_meta(tags=["transform"], safety_level="high", determinism="nondeterministic")

        r_a = _make_result("a.fetch", 0.5, meta_a)
        r_b = _make_result("b.parse", 0.5, meta_b)
        r_c = _make_result("c.transform", 0.5, meta_c)

        results = [r_c, r_a, r_b]  # deliberately unsorted

        order1 = [r.name for r in rank_discovered_skills("fetch data", results)]
        order2 = [r.name for r in rank_discovered_skills("fetch data", results)]
        order3 = [r.name for r in rank_discovered_skills("fetch data", results)]

        assert order1 == order2 == order3

    def test_ranking_stable_across_registry_rebuilds(self):
        from src.capabilities.registry.deterministic_ranking import (
            rank_discovered_skills,
        )

        meta_a = _make_manifest_meta(tags=["fetch"], cost_estimate={"latency": 10, "resources": "low"})
        meta_b = _make_manifest_meta(tags=["parse"], cost_estimate={"latency": 50, "resources": "medium"})

        # Build A (one order)
        results_a = [
            _make_result("b.parse", 0.7, meta_b),
            _make_result("a.fetch", 0.7, meta_a),
        ]
        order_a = [r.name for r in rank_discovered_skills("fetch", results_a)]

        # Build B (reversed order)
        results_b = [
            _make_result("a.fetch", 0.7, meta_a),
            _make_result("b.parse", 0.7, meta_b),
        ]
        order_b = [r.name for r in rank_discovered_skills("fetch", results_b)]

        assert order_a == order_b

    def test_ranking_stable_regardless_of_insertion_order(self):
        from src.capabilities.registry.deterministic_ranking import (
            rank_discovered_skills,
        )

        meta = _make_manifest_meta(tags=["transform"])

        # Insertion order A
        r1 = [r.name for r in rank_discovered_skills(
            "transform text",
            [_make_result("c", 0.3, meta), _make_result("a", 0.3, meta), _make_result("b", 0.3, meta)],
        )]
        # Insertion order B
        r2 = [r.name for r in rank_discovered_skills(
            "transform text",
            [_make_result("b", 0.3, meta), _make_result("c", 0.3, meta), _make_result("a", 0.3, meta)],
        )]

        assert r1 == r2

    # ── Priority: A.  Exact tag match ──────────────────────────────────

    def test_exact_tag_match_ranks_higher(self):
        from src.capabilities.registry.deterministic_ranking import (
            rank_discovered_skills,
        )

        meta_tagged = _make_manifest_meta(tags=["fetch"])
        meta_untagged = _make_manifest_meta(tags=["compute"])

        r_tagged = _make_result("tagged.fetch", 0.5, meta_tagged)
        r_untagged = _make_result("untagged.compute", 0.9, meta_untagged)

        order = [r.name for r in rank_discovered_skills("fetch this file", [r_untagged, r_tagged])]
        assert order[0] == "tagged.fetch"

    # ── Priority: B.  Schema compatibility ─────────────────────────────

    def test_schema_compatibility_ranks_higher(self):
        from src.capabilities.registry.deterministic_ranking import (
            rank_discovered_skills,
        )

        meta_match = _make_manifest_meta(
            input_types={"url": "str"},
            output_types={"data": "str"},
        )
        meta_nomatch = _make_manifest_meta(
            input_types={"path": "str"},
            output_types={"lines": "int"},
        )

        r_match = _make_result("match", 0.5, meta_match)
        r_nomatch = _make_result("nomatch", 0.9, meta_nomatch)

        context = {"input_hints": {"url": "str"}, "output_hints": {"data": "str"}}
        order = [r.name for r in rank_discovered_skills("query", [r_nomatch, r_match], context)]
        assert order[0] == "match"

    def test_schema_compatibility_counts_multiple_matches(self):
        from src.capabilities.registry.deterministic_ranking import (
            compute_schema_compatibility,
        )

        meta = _make_manifest_meta(
            input_types={"url": "str", "headers": "dict"},
            output_types={"status": "int", "body": "str"},
        )
        skill = FakeSkill("multi", meta)

        context = {
            "input_hints": {"url": "str", "headers": "dict", "timeout": "int"},
            "output_hints": {"status": "int", "body": "str"},
        }
        score = compute_schema_compatibility("", skill, context)
        assert score == 4  # url, headers, status, body

    # ── Priority: C.  Safety level ─────────────────────────────────────

    def test_safety_level_ranks_correctly(self):
        from src.capabilities.registry.deterministic_ranking import (
            rank_discovered_skills,
        )

        meta_high = _make_manifest_meta(safety_level="high")
        meta_med = _make_manifest_meta(safety_level="medium")
        meta_low = _make_manifest_meta(safety_level="low")

        results = [
            _make_result("low", 0.5, meta_low),
            _make_result("high", 0.5, meta_high),
            _make_result("med", 0.5, meta_med),
        ]
        order = [r.name for r in rank_discovered_skills("query", results)]
        assert order == ["high", "med", "low"]

    # ── Priority: D.  Determinism ──────────────────────────────────────

    def test_determinism_ranks_correctly(self):
        from src.capabilities.registry.deterministic_ranking import (
            rank_discovered_skills,
        )

        meta_pure = _make_manifest_meta(determinism="pure")
        meta_impure = _make_manifest_meta(determinism="impure")
        meta_nondet = _make_manifest_meta(determinism="nondeterministic")

        results = [
            _make_result("nondet", 0.5, meta_nondet),
            _make_result("impure", 0.5, meta_impure),
            _make_result("pure", 0.5, meta_pure),
        ]
        order = [r.name for r in rank_discovered_skills("query", results)]
        assert order == ["pure", "impure", "nondet"]

    # ── Priority: E.  Cost ─────────────────────────────────────────────

    def test_lower_latency_ranks_higher(self):
        from src.capabilities.registry.deterministic_ranking import (
            rank_discovered_skills,
        )

        meta_fast = _make_manifest_meta(cost_estimate={"latency": 10, "resources": "low"})
        meta_slow = _make_manifest_meta(cost_estimate={"latency": 999, "resources": "low"})

        results = [
            _make_result("slow", 0.5, meta_slow),
            _make_result("fast", 0.5, meta_fast),
        ]
        order = [r.name for r in rank_discovered_skills("query", results)]
        assert order == ["fast", "slow"]

    def test_lower_resources_ranks_higher(self):
        from src.capabilities.registry.deterministic_ranking import (
            rank_discovered_skills,
        )

        meta_low = _make_manifest_meta(cost_estimate={"latency": 50, "resources": "low"})
        meta_med = _make_manifest_meta(cost_estimate={"latency": 50, "resources": "medium"})
        meta_high = _make_manifest_meta(cost_estimate={"latency": 50, "resources": "high"})

        results = [
            _make_result("high_res", 0.5, meta_high),
            _make_result("med_res", 0.5, meta_med),
            _make_result("low_res", 0.5, meta_low),
        ]
        order = [r.name for r in rank_discovered_skills("query", results)]
        assert order == ["low_res", "med_res", "high_res"]

    # ── Priority: F.  Embedding similarity ─────────────────────────────

    def test_higher_embedding_score_ranks_higher(self):
        from src.capabilities.registry.deterministic_ranking import (
            rank_discovered_skills,
        )

        meta = _make_manifest_meta()
        results = [
            _make_result("low_score", 0.3, meta),
            _make_result("high_score", 0.9, meta),
        ]
        order = [r.name for r in rank_discovered_skills("query", results)]
        assert order == ["high_score", "low_score"]

    # ── Priority: G.  Name tiebreaker ──────────────────────────────────

    def test_name_breaks_ties_deterministically(self):
        from src.capabilities.registry.deterministic_ranking import (
            rank_discovered_skills,
        )

        meta = _make_manifest_meta()
        results = [
            _make_result("zulu", 0.5, meta),
            _make_result("alpha", 0.5, meta),
        ]
        order = [r.name for r in rank_discovered_skills("query", results)]
        assert order == ["alpha", "zulu"]

    # ── Missing metadata ───────────────────────────────────────────────

    def test_missing_manifest_metadata_raises(self):
        from src.capabilities.registry.deterministic_ranking import (
            rank_discovered_skills,
        )

        # FakeSkill with manifest but NO metadata attached
        skill_no_meta = FakeSkill("no-meta")  # manifest_metadata=None → manifest.metadata is None
        from src.capabilities.registry.skill_discovery_result import SkillSearchResult

        result = SkillSearchResult(
            name="no-meta",
            score=0.5,
            version="1.0",
            skill_metadata={},
            primitive_metadata=[],
            skill=skill_no_meta,
        )
        with pytest.raises(AttributeError):
            rank_discovered_skills("query", [result])


# ═══════════════════════════════════════════════════════════════════════════
# compute_schema_compatibility tests
# ═══════════════════════════════════════════════════════════════════════════

class TestComputeSchemaCompatibility:
    """Tests for ``compute_schema_compatibility``."""

    def test_no_hints_returns_zero(self):
        from src.capabilities.registry.deterministic_ranking import (
            compute_schema_compatibility,
        )

        meta = _make_manifest_meta(input_types={"url": "str"})
        skill = FakeSkill("s", meta)
        assert compute_schema_compatibility("", skill, {}) == 0

    def test_none_hints_returns_zero(self):
        from src.capabilities.registry.deterministic_ranking import (
            compute_schema_compatibility,
        )

        meta = _make_manifest_meta(input_types={"url": "str"})
        skill = FakeSkill("s", meta)
        assert compute_schema_compatibility("", skill, {"input_hints": None}) == 0

    def test_exact_field_match_counts(self):
        from src.capabilities.registry.deterministic_ranking import (
            compute_schema_compatibility,
        )

        meta = _make_manifest_meta(input_types={"url": "str", "method": "str"})
        skill = FakeSkill("s", meta)
        score = compute_schema_compatibility(
            "", skill, {"input_hints": {"url": "str", "method": "str"}}
        )
        assert score == 2

    def test_partial_match_counts_correctly(self):
        from src.capabilities.registry.deterministic_ranking import (
            compute_schema_compatibility,
        )

        meta = _make_manifest_meta(input_types={"url": "str"})
        skill = FakeSkill("s", meta)
        score = compute_schema_compatibility(
            "", skill, {"input_hints": {"url": "str", "unknown_field": "int"}}
        )
        assert score == 1

    def test_output_hints_matched(self):
        from src.capabilities.registry.deterministic_ranking import (
            compute_schema_compatibility,
        )

        meta = _make_manifest_meta(output_types={"result": "str"})
        skill = FakeSkill("s", meta)
        score = compute_schema_compatibility(
            "", skill, {"output_hints": {"result": "str"}}
        )
        assert score == 1


# ═══════════════════════════════════════════════════════════════════════════
# extract_query_tag tests
# ═══════════════════════════════════════════════════════════════════════════

class TestExtractQueryTag:
    """Tests for ``extract_query_tag``."""

    def test_known_tag_detected(self):
        from src.capabilities.registry.deterministic_ranking import (
            extract_query_tag,
        )

        assert extract_query_tag("fetch this file") == "fetch"
        assert extract_query_tag("parse the json") == "parse"
        assert extract_query_tag("transform the data") == "transform"

    def test_no_tag_returns_none(self):
        from src.capabilities.registry.deterministic_ranking import (
            extract_query_tag,
        )

        assert extract_query_tag("hello world") is None
        assert extract_query_tag("") is None

    def test_case_insensitive(self):
        from src.capabilities.registry.deterministic_ranking import (
            extract_query_tag,
        )

        assert extract_query_tag("FETCH file") == "fetch"
        assert extract_query_tag("Parse JSON") == "parse"

    def test_longest_tag_matched_first(self):
        from src.capabilities.registry.deterministic_ranking import (
            extract_query_tag,
        )

        # "summarize" is longer than "summarise" but both exist;
        # longer tags are checked first, so "summarize" wins
        assert extract_query_tag("summarize this text") == "summarize"

    def test_deterministic_on_repeat(self):
        from src.capabilities.registry.deterministic_ranking import (
            extract_query_tag,
        )

        assert extract_query_tag("download the file") == extract_query_tag("download the file")
