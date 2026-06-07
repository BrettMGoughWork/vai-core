"""
Tests for semantic skill search (Phase 3.4.3).

Covers: ranked results, deterministic ordering, zero-score exclusion,
and missing embedding_fn error.
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.registry.skill_search import search_skills, cosine_similarity
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill


# ---------------------------------------------------------------------------
# Fake primitive
# ---------------------------------------------------------------------------

class FakePrimitive(PrimitiveBase):
    def __init__(self, *, name: str, description: str = "", primitive_type: PrimitiveType = PrimitiveType.PYTHON) -> None:
        super().__init__(name=name, description=description, primitive_type=primitive_type)

    def validate_args(self, _args: dict) -> None:
        return

    def execute(self, _args: dict, _context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data=None)


# ---------------------------------------------------------------------------
# Fake embedding function — word‑vector mapping for deterministic similarity
# ---------------------------------------------------------------------------

_WORD_VECTORS: dict[str, list[float]] = {
    "file":   [1.0, 0.0, 0.0],
    "read":   [0.9, 0.1, 0.0],
    "write":  [0.1, 0.9, 0.0],
    "http":   [0.0, 0.0, 1.0],
    "fetch":  [0.0, 0.1, 0.9],
    "echo":   [0.0, 1.0, 0.0],
    "print":  [0.1, 0.8, 0.1],
    "data":   [0.5, 0.0, 0.5],
    "transform": [0.3, 0.3, 0.4],
}


def _fake_embed(text: str) -> list[float]:
    """Sum word vectors — words with similar meanings get similar vectors."""
    dim = 3
    result = [0.0] * dim
    for word in text.lower().replace("\n", " ").split():
        vec = _WORD_VECTORS.get(word.strip(":,"))
        if vec:
            for i in range(dim):
                result[i] += vec[i]
    # Return zero vector if no known words (produces 0.0 similarity)
    if all(v == 0.0 for v in result):
        return result
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill(name: str, description: str, primitive_names: list[str] | None = None, steps: list[dict] | None = None) -> CapabilitySkill:
    if primitive_names is None:
        primitive_names = ["echo"]
    if steps is None:
        steps = [{"call": "echo", "args": {}}]

    prim_registry = PrimitiveRegistry()
    for pn in primitive_names:
        prim_registry.register(pn, FakePrimitive(name=pn))

    manifest = SkillManifest(name=name, description=description, primitives=primitive_names, inputs={}, steps=steps)
    return CapabilitySkill.from_manifest(manifest, prim_registry)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def context() -> dict:
    return {"embedding_fn": _fake_embed}


@pytest.fixture
def empty_context() -> dict:
    return {}


@pytest.fixture
def populated_registry() -> CapabilitySkillRegistry:
    registry = CapabilitySkillRegistry()
    registry.register(_make_skill("file.read", "read a file from disk", primitive_names=["file.read"], steps=[{"call": "file.read", "args": {"path": ""}}]))
    registry.register(_make_skill("file.write", "write data to a file", primitive_names=["file.write"], steps=[{"call": "file.write", "args": {"path": "", "data": ""}}]))
    registry.register(_make_skill("http.fetch", "fetch a URL over HTTP", primitive_names=["http.fetch"], steps=[{"call": "http.fetch", "args": {"url": ""}}]))
    return registry


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_zero_vector_returns_zero(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_opposite_vectors(self) -> None:
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# Search skills
# ---------------------------------------------------------------------------

class TestSearchSkills:
    def test_query_returns_ranked_results(self, populated_registry: CapabilitySkillRegistry, context: dict) -> None:
        results = search_skills("read file", populated_registry, context)
        assert len(results) >= 1
        # Scores should be descending
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_higher_similarity_ranks_above(self, populated_registry: CapabilitySkillRegistry, context: dict) -> None:
        results = search_skills("read file", populated_registry, context)
        assert len(results) >= 2
        # "file.read" should rank above "http.fetch" for "read file" query
        names = [r["name"] for r in results]
        idx_read = names.index("file.read")
        idx_http = names.index("http.fetch")
        assert idx_read < idx_http

    def test_deterministic_ordering(self, populated_registry: CapabilitySkillRegistry, context: dict) -> None:
        results1 = search_skills("file read write", populated_registry, context)
        results2 = search_skills("file read write", populated_registry, context)
        assert [r["name"] for r in results1] == [r["name"] for r in results2]
        assert [r["score"] for r in results1] == [r["score"] for r in results2]

    def test_zero_similarity_excluded(self, populated_registry: CapabilitySkillRegistry, context: dict) -> None:
        # Query with no known words → all zero embeddings → all excluded
        results = search_skills("zzzunknown query", populated_registry, context)
        assert len(results) == 0

    def test_missing_embedding_fn_raises(self, populated_registry: CapabilitySkillRegistry, empty_context: dict) -> None:
        with pytest.raises(ValueError, match="missing embedding_fn"):
            search_skills("read file", populated_registry, empty_context)
