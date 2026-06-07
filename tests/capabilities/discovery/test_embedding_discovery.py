"""
Tests for embedding-based primitive discovery (Phase 3.2.5).

Covers: ranked cosine-similarity search, zero-score exclusion,
missing embedding_fn error, and deterministic ordering.
"""

from __future__ import annotations

from typing import Any, Dict, List

import math
import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.discovery.embedding_discovery import (
    build_primitive_embedding,
    discover_primitives,
    _cosine_similarity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class StubPrimitive(PrimitiveBase):
    """A primitive with controllable name, description, and execute docstring."""

    def __init__(
        self,
        *,
        name: str,
        description: str = "",
        primitive_type: PrimitiveType = PrimitiveType.PYTHON,
        execute_doc: str = "",
    ) -> None:
        super().__init__(name=name, description=description, primitive_type=primitive_type)
        self._execute_doc = execute_doc

    def validate_args(self, args: dict) -> None:
        pass

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        """%s"""  # placeholder; overridden via __doc__ below
        return PrimitiveResult(status="success", data=None)


# Override the execute method's docstring after construction
def _make_stub(
    name: str,
    description: str = "",
    execute_doc: str = "",
) -> StubPrimitive:
    p = StubPrimitive(name=name, description=description)
    p.execute.__func__.__doc__ = execute_doc
    return p


def _hash_embed(text: str) -> List[float]:
    """Deterministic embedding from text hash (32 dims)."""
    import hashlib
    h = hashlib.sha256(text.encode()).digest()
    return [float(b) / 255.0 for b in h[:32]]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry() -> PrimitiveRegistry:
    reg = PrimitiveRegistry()
    reg.register("file.read", _make_stub("file.read", "Read a file from disk", "read(path)"))
    reg.register("file.write", _make_stub("file.write", "Write data to a file", "write(path, data)"))
    reg.register("net.fetch", _make_stub("net.fetch", "Fetch a URL over HTTP", "fetch(url)"))
    reg.register("db.query", _make_stub("db.query", "Run a SQL query", "query(sql)"))
    reg.register("math.add", _make_stub("math.add", "Add two numbers", "add(a, b)"))
    return reg


@pytest.fixture
def ctx() -> Dict[str, Any]:
    return {"embedding_fn": _hash_embed}


# ---------------------------------------------------------------------------
# build_primitive_embedding
# ---------------------------------------------------------------------------

class TestBuildPrimitiveEmbedding:
    def test_returns_embedding_vector(self, registry: PrimitiveRegistry, ctx: Dict[str, Any]) -> None:
        p = registry.get("file.read")
        assert p is not None
        vec = build_primitive_embedding(p, ctx)
        assert isinstance(vec, list)
        assert len(vec) == 32
        assert all(isinstance(v, float) for v in vec)

    def test_missing_embedding_fn_raises(self, registry: PrimitiveRegistry) -> None:
        p = registry.get("file.read")
        assert p is not None
        with pytest.raises(ValueError, match="missing embedding_fn"):
            build_primitive_embedding(p, {})

    def test_different_primitives_yield_different_embeddings(
        self, registry: PrimitiveRegistry, ctx: Dict[str, Any]
    ) -> None:
        a = registry.get("file.read")
        b = registry.get("math.add")
        assert a is not None and b is not None
        vec_a = build_primitive_embedding(a, ctx)
        vec_b = build_primitive_embedding(b, ctx)
        assert vec_a != vec_b  # different text → different hash → different vector


# ---------------------------------------------------------------------------
# discover_primitives
# ---------------------------------------------------------------------------

class TestDiscoverPrimitives:
    def test_returns_ranked_results(
        self, registry: PrimitiveRegistry, ctx: Dict[str, Any]
    ) -> None:
        results = discover_primitives("read file", registry, ctx)
        assert len(results) >= 1
        for i in range(len(results) - 1):
            assert results[i]["score"] >= results[i + 1]["score"]

    def test_excludes_zero_similarity(
        self, registry: PrimitiveRegistry, ctx: Dict[str, Any]
    ) -> None:
        """With hash-based embeddings, every non-identical pair has non-zero
        cosine similarity.  Use a stub that always returns a zero vector for
        the query while primitives return non-zero vectors to get zero scores."""
        reg = PrimitiveRegistry()
        p = _make_stub("a", "description a")
        reg.register("a", p)

        ctx_zero = {
            "embedding_fn": lambda text: [0.0] * 32 if text != p.name else [1.0] * 3 + [0.0] * 29
        }
        # Query "zzz" → zero vector, primitive embedding non-zero → cosine = 0
        results = discover_primitives("zzz", reg, ctx_zero)
        assert results == []

    def test_missing_embedding_fn_raises(
        self, registry: PrimitiveRegistry
    ) -> None:
        with pytest.raises(ValueError, match="missing embedding_fn"):
            discover_primitives("query", registry, {})

    def test_result_structure(
        self, registry: PrimitiveRegistry, ctx: Dict[str, Any]
    ) -> None:
        results = discover_primitives("database", registry, ctx)
        for r in results:
            assert "name" in r
            assert "primitive" in r
            assert "score" in r
            assert isinstance(r["name"], str)
            assert isinstance(r["primitive"], PrimitiveBase)
            assert isinstance(r["score"], float)
            assert r["score"] > 0

    def test_identical_query_exact_match_scores_highest(
        self, registry: PrimitiveRegistry, ctx: Dict[str, Any]
    ) -> None:
        """Searching for the exact text of a primitive's embedding should
        rank that primitive first (cosine with itself ≈ 1.0)."""
        p = registry.get("file.read")
        assert p is not None
        # Construct the same text the embedder builds
        target_text = f"{p.name}\n{p.description}\n{(p.execute.__doc__ or '').strip()}"
        results = discover_primitives(target_text, registry, ctx)
        assert len(results) > 0
        # The top result should have cosine similarity close to 1.0
        assert results[0]["score"] > 0.99
        assert results[0]["name"] == "file.read"


# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = [1.0, 2.0, 3.0]
        assert math.isclose(_cosine_similarity(v, v), 1.0)

    def test_orthogonal_vectors(self) -> None:
        assert math.isclose(_cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_zero_vectors(self) -> None:
        assert _cosine_similarity([], []) == 0.0
        assert _cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0

    def test_different_lengths(self) -> None:
        """zip stops at the shorter vector — length mismatch should not crash."""
        result = _cosine_similarity([1.0, 0.0, 0.0], [1.0])
        # dot = 1*1 = 1, norm1 = 1, norm2 = 1 → cosine = 1.0
        assert result == 1.0
