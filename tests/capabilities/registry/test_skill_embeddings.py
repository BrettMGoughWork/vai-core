"""
Tests for skill embedding generation (Phase 3.4.2).

Covers: embedding text contents, deterministic output, and error handling.
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.registry.skill_embeddings import (
    build_skill_embedding,
    build_query_embedding,
)
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
# Fake embedding function — records the text it was called with
# ---------------------------------------------------------------------------

class SpyEmbeddingFn:
    """Returns a fixed vector and records the last text it was called with."""

    def __init__(self, vector: list[float] | None = None) -> None:
        self._vector = vector or [1.0, 0.0, 0.0]
        self.last_text: str | None = None

    def __call__(self, text: str) -> list[float]:
        self.last_text = text
        return list(self._vector)


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
def spy_fn() -> SpyEmbeddingFn:
    return SpyEmbeddingFn()


@pytest.fixture
def context(spy_fn: SpyEmbeddingFn) -> dict:
    return {"embedding_fn": spy_fn}


# ---------------------------------------------------------------------------
# Skill embedding
# ---------------------------------------------------------------------------

class TestBuildSkillEmbedding:
    def test_includes_skill_name(self, spy_fn: SpyEmbeddingFn, context: dict) -> None:
        skill = _make_skill("my-skill", "does things")
        build_skill_embedding(skill, context)
        assert spy_fn.last_text is not None
        assert "my-skill" in spy_fn.last_text

    def test_includes_description(self, spy_fn: SpyEmbeddingFn, context: dict) -> None:
        skill = _make_skill("my-skill", "does amazing things")
        build_skill_embedding(skill, context)
        assert spy_fn.last_text is not None
        assert "does amazing things" in spy_fn.last_text

    def test_includes_step_summaries(self, spy_fn: SpyEmbeddingFn, context: dict) -> None:
        skill = _make_skill("multi-step", "multi-step skill", primitive_names=["a", "b"], steps=[{"call": "a", "args": {"x": 1}}, {"call": "b", "args": {"y": 2, "z": 3}}])
        build_skill_embedding(skill, context)
        assert spy_fn.last_text is not None
        assert "step: a args: x" in spy_fn.last_text
        assert "step: b args: y,z" in spy_fn.last_text

    def test_deterministic_output(self, spy_fn: SpyEmbeddingFn, context: dict) -> None:
        skill = _make_skill("det", "deterministic test", steps=[{"call": "echo", "args": {"b": 2, "a": 1}}])
        build_skill_embedding(skill, context)
        text1 = spy_fn.last_text
        spy_fn.last_text = None
        build_skill_embedding(skill, context)
        text2 = spy_fn.last_text
        assert text1 == text2

    def test_missing_embedding_fn_raises(self) -> None:
        skill = _make_skill("test", "desc")
        with pytest.raises(ValueError, match="missing embedding_fn"):
            build_skill_embedding(skill, {})


# ---------------------------------------------------------------------------
# Query embedding
# ---------------------------------------------------------------------------

class TestBuildQueryEmbedding:
    def test_passes_query_to_fn(self, spy_fn: SpyEmbeddingFn, context: dict) -> None:
        result = build_query_embedding("find files", context)
        assert spy_fn.last_text == "find files"
        assert result == [1.0, 0.0, 0.0]

    def test_missing_embedding_fn_raises(self) -> None:
        with pytest.raises(ValueError, match="missing embedding_fn"):
            build_query_embedding("query", {})
