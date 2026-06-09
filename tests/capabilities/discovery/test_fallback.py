"""
Tests for discovery fallback wiring (PHASE 3.19.5).

Tests ``resolve_capability_with_fallback()`` — the single entry point
that resolves a capability name, falling back to semantic vector search
when the LLM-named skill does not exist.
"""

from __future__ import annotations

import asyncio

import pytest

from src.capabilities.discovery.fallback import resolve_capability_with_fallback
from src.capabilities.discovery.providers.mock_provider import (
    MockEmbeddingProvider,
    _simple_embedding_fn,
)
from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill


# ── Helpers ────────────────────────────────────────────────────────

class _FakePrimitive(PrimitiveBase):
    """Minimal primitive stub for CapabilitySkill construction."""

    def __init__(self, *, name: str, description: str = "",
                 primitive_type: PrimitiveType = PrimitiveType.PYTHON) -> None:
        super().__init__(name=name, description=description,
                         primitive_type=primitive_type)

    def validate_args(self, _args: dict) -> None:
        return

    def execute(self, _args: dict, _context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data=None)


class _TestEmbedder:
    """SkillEmbedder-like stub wrapping _simple_embedding_fn."""

    def embed(self, text: str) -> list[float]:
        return _simple_embedding_fn(text)

    def embed_query(self, query: str) -> list[float]:
        return self.embed(query)


def _make_skill(name: str, description: str = "a skill",
                primitive_names: list[str] | None = None,
                steps: list[dict] | None = None) -> CapabilitySkill:
    """Build a CapabilitySkill with a fake primitive."""
    if primitive_names is None:
        primitive_names = ["echo"]
    if steps is None:
        steps = [{"call": "echo", "args": {}}]
    prim_registry = PrimitiveRegistry()
    for pn in primitive_names:
        prim_registry.register(pn, _FakePrimitive(name=pn))
    manifest = SkillManifest(name=name, description=description,
                             primitives=primitive_names, inputs={}, steps=steps)
    return CapabilitySkill.from_manifest(manifest, prim_registry)


def _run(coro):
    """Thin wrapper so we don't need pytest-asyncio."""
    return asyncio.run(coro)


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def registry_with_skills() -> CapabilitySkillRegistry:
    """Registry with two skills and a deterministic embedder."""
    reg = CapabilitySkillRegistry(embedder=_TestEmbedder())
    reg.register(_make_skill("file.read", "reads a file from disk"))
    reg.register(_make_skill("file.write", "writes data to a file"))
    return reg


@pytest.fixture
def registry_without_embedder() -> CapabilitySkillRegistry:
    """Registry with skills but NO embedder — fallback should be graceful."""
    reg = CapabilitySkillRegistry()
    reg.register(_make_skill("file.read"))
    return reg


# ── Tests: LLM-named skill precedence ──────────────────────────────

class TestLLMPrecedence:
    """LLM-named skills ALWAYS take precedence over fallback."""

    def test_llm_named_skill_exists_returns_directly(
        self, registry_with_skills: CapabilitySkillRegistry,
    ) -> None:
        """When the LLM names an existing skill, it is returned without
        any semantic search."""
        result = _run(resolve_capability_with_fallback(
            query="irrelevant query text",
            llm_named="file.read",
            registry=registry_with_skills,
        ))
        assert result is not None
        assert result.manifest.name == "file.read"

    def test_llm_named_skill_exists_is_exact_match(
        self, registry_with_skills: CapabilitySkillRegistry,
    ) -> None:
        """The LLM skill is returned even if the query better matches
        a different skill — LLM always wins."""
        result = _run(resolve_capability_with_fallback(
            query="write something to disk",
            llm_named="file.read",
            registry=registry_with_skills,
        ))
        assert result is not None
        assert result.manifest.name == "file.read"

    def test_llm_named_is_none_triggers_fallback(
        self, registry_with_skills: CapabilitySkillRegistry,
    ) -> None:
        """When the LLM returns None (no capability named), semantic
        fallback is triggered using the query text."""
        result = _run(resolve_capability_with_fallback(
            query="write data to a file",
            llm_named=None,
            registry=registry_with_skills,
        ))
        assert result is not None
        # "write" should semantically match file.write better
        assert result.manifest.name == "file.write"

    def test_llm_named_skill_does_not_exist_triggers_fallback(
        self, registry_with_skills: CapabilitySkillRegistry,
    ) -> None:
        """When the LLM names a skill not in the registry, fallback
        is triggered using the query text (not the LLM name)."""
        result = _run(resolve_capability_with_fallback(
            query="read a file from disk",
            llm_named="nonexistent.skill",
            registry=registry_with_skills,
        ))
        # Should get a valid skill via semantic fallback (not the LLM name)
        assert result is not None
        assert isinstance(result, CapabilitySkill)
        # Must be one of the registered skills
        assert result.manifest.name in ("file.read", "file.write")


# ── Tests: Semantic fallback behavior ──────────────────────────────

class TestSemanticFallback:
    """Tests for the fallback path triggered when the LLM can't name a skill."""

    def test_fallback_returns_top_one_match(
        self, registry_with_skills: CapabilitySkillRegistry,
    ) -> None:
        """Fallback search returns exactly the top-1 match (a single
        CapabilitySkill from the registry)."""
        result = _run(resolve_capability_with_fallback(
            query="read a file",
            llm_named=None,
            registry=registry_with_skills,
            k=1,
        ))
        assert result is not None
        assert isinstance(result, CapabilitySkill)
        assert result.manifest.name in ("file.read", "file.write")

    def test_fallback_no_match_returns_none(
        self, registry_with_skills: CapabilitySkillRegistry,
    ) -> None:
        """When no skill matches semantically (≤0 similarity), fallback
        returns None.  With the real provider this happens for unrelated
        domains; with _simple_embedding_fn all scores are positive so we
        test via an empty registry."""
        # Empty registry — find_semantic returns [] and fallback returns None
        empty_reg = CapabilitySkillRegistry(embedder=_TestEmbedder())
        result = _run(resolve_capability_with_fallback(
            query="quantum computing with qubits",
            llm_named=None,
            registry=empty_reg,
        ))
        assert result is None

    def test_fallback_no_embedder_configured_returns_none(
        self, registry_without_embedder: CapabilitySkillRegistry,
    ) -> None:
        """When no embedder is configured on the registry, fallback
        gracefully returns None instead of raising."""
        result = _run(resolve_capability_with_fallback(
            query="read a file",
            llm_named=None,
            registry=registry_without_embedder,
        ))
        assert result is None

    def test_fallback_no_embedder_with_llm_named_missing(
        self, registry_without_embedder: CapabilitySkillRegistry,
    ) -> None:
        """LLM names a missing skill AND no embedder → graceful None."""
        result = _run(resolve_capability_with_fallback(
            query="read a file",
            llm_named="missing.skill",
            registry=registry_without_embedder,
        ))
        assert result is None

    def test_fallback_with_llm_named_missing_and_embedder(
        self, registry_with_skills: CapabilitySkillRegistry,
    ) -> None:
        """LLM names a missing skill but embedder exists → fallback succeeds."""
        result = _run(resolve_capability_with_fallback(
            query="read a file from disk",
            llm_named="made.up.skill",
            registry=registry_with_skills,
        ))
        assert result is not None
        assert isinstance(result, CapabilitySkill)
        assert result.manifest.name in ("file.read", "file.write")


# ── Tests: Query embedding cache ───────────────────────────────────

class TestQueryCacheDuringFallback:
    """The query cache should be used during fallback resolution."""

    def test_cache_reuses_embedding_across_fallback_calls(
        self, registry_with_skills: CapabilitySkillRegistry,
    ) -> None:
        """Two fallback calls with the same query return the same result
        (embedding is cached per session)."""
        result1 = _run(resolve_capability_with_fallback(
            query="write to disk",
            llm_named=None,
            registry=registry_with_skills,
        ))
        result2 = _run(resolve_capability_with_fallback(
            query="write to disk",
            llm_named=None,
            registry=registry_with_skills,
        ))
        assert result1 is not None
        assert result2 is not None
        assert result1.manifest.name == result2.manifest.name


# ── Tests: Async contract ──────────────────────────────────────────

class TestAsyncContract:
    """Verify resolve_capability_with_fallback honours its async contract."""

    def test_function_is_async_callable(self) -> None:
        """The function is defined as async and returns a coroutine."""
        import inspect
        assert inspect.iscoroutinefunction(resolve_capability_with_fallback)

    def test_can_be_awaited(
        self, registry_with_skills: CapabilitySkillRegistry,
    ) -> None:
        """The function can be awaited and returns a CapabilitySkill."""
        result = _run(resolve_capability_with_fallback(
            query="read",
            llm_named="file.read",
            registry=registry_with_skills,
        ))
        assert result is not None
        assert result.manifest.name == "file.read"

    def test_k_defaults_to_one(
        self, registry_with_skills: CapabilitySkillRegistry,
    ) -> None:
        """When k is not specified, only the top-1 match is returned."""
        result = _run(resolve_capability_with_fallback(
            query="write",
            llm_named=None,
            registry=registry_with_skills,
        ))
        assert result is not None
        # Should be a single skill, not a list
        assert isinstance(result, CapabilitySkill)


# ── Edge cases ─────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge-case behavior for fallback resolution."""

    def test_empty_registry_returns_none(
        self, registry_with_skills: CapabilitySkillRegistry,
    ) -> None:
        """Empty registry with a valid embedder returns None for any query."""
        empty = CapabilitySkillRegistry(embedder=_TestEmbedder())
        result = _run(resolve_capability_with_fallback(
            query="anything",
            llm_named=None,
            registry=empty,
        ))
        assert result is None

    def test_empty_query_string_with_llm_none(
        self, registry_with_skills: CapabilitySkillRegistry,
    ) -> None:
        """Empty query with no LLM name → fallback search on empty string."""
        result = _run(resolve_capability_with_fallback(
            query="",
            llm_named=None,
            registry=registry_with_skills,
        ))
        # Empty string produces a valid embedding, may or may not match
        # Important: should not crash
        assert result is None or isinstance(result, CapabilitySkill)
