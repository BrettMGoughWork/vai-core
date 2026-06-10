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

    def test_includes_signature_from_inputs(self, spy_fn: SpyEmbeddingFn, context: dict) -> None:
        """PHASE 3.19.2: Signature is derived from input schema properties."""
        prim_registry = PrimitiveRegistry()
        prim_registry.register("search", FakePrimitive(name="search"))
        manifest = SkillManifest(
            name="search_urls",
            description="search the web",
            primitives=["search"],
            inputs={"properties": {"query": {"type": "string"}, "max_results": {"type": "number"}}},
            steps=[{"call": "search", "args": {"query": "", "max_results": 0}}],
        )
        skill = CapabilitySkill.from_manifest(manifest, prim_registry)
        build_skill_embedding(skill, context)
        assert spy_fn.last_text is not None
        assert "signature:" in spy_fn.last_text
        assert "query:string" in spy_fn.last_text
        assert "max_results:number" in spy_fn.last_text

    def test_includes_signature_from_outputs(self, spy_fn: SpyEmbeddingFn, context: dict) -> None:
        """PHASE 3.19.2: Signature includes outputs when present."""
        from types import SimpleNamespace
        prim_registry = PrimitiveRegistry()
        prim_registry.register("search", FakePrimitive(name="search"))
        manifest = SkillManifest(
            name="search_urls",
            description="search the web",
            primitives=["search"],
            inputs={"properties": {"query": {"type": "string"}}},
            steps=[{"call": "search", "args": {"query": ""}}],
        )
        # Attach outputs via a namespace wrapper (outputs is not in SkillManifest.__init__)
        raw_outputs = {"outputs": {"properties": {"results": {"type": "array"}}}}
        # We can't easily set outputs on SkillManifest, so test via _build_skill_text directly
        skill = CapabilitySkill.from_manifest(manifest, prim_registry)
        # Monkey-patch outputs onto the manifest
        skill.manifest.outputs = raw_outputs.get("outputs", {})  # type: ignore[attr-defined]
        build_skill_embedding(skill, context)
        assert spy_fn.last_text is not None
        assert "results:array" in spy_fn.last_text

    def test_no_inputs_no_signature(self, spy_fn: SpyEmbeddingFn, context: dict) -> None:
        """No inputs or outputs → no signature line."""
        skill = _make_skill("minimal", "just a description")
        build_skill_embedding(skill, context)
        assert spy_fn.last_text is not None
        assert "signature:" not in spy_fn.last_text


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


# ---------------------------------------------------------------------------
# Vector store count & hot-reload e2e (PHASE 3.19.7)
# ---------------------------------------------------------------------------

class TestVectorStoreCountAfterRegistrations:
    """PHASE 3.19.7: Vector store count matches N registered skills."""

    def test_empty_registry_has_empty_vector_store(self) -> None:
        """Registry with no skills → vector store length 0."""
        from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
        from src.capabilities.discovery.vector_store import VectorStore
        registry = CapabilitySkillRegistry()
        store = VectorStore()
        registry.set_vector_store(store)
        assert len(store) == 0

    def test_vector_store_count_matches_registration_count(self) -> None:
        """After N registrations (with auto‑embedding), vector store has length N."""
        from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
        from src.capabilities.discovery.vector_store import VectorStore
        from src.capabilities.discovery.embedder import SkillEmbedder
        from src.capabilities.discovery.providers.mock_provider import MockEmbeddingProvider

        registry = CapabilitySkillRegistry()
        embedder = SkillEmbedder(provider=MockEmbeddingProvider(dimensions=8), cache_enabled=False)
        registry.set_embedder(embedder)

        store = VectorStore()
        registry.set_vector_store(store)

        # register() auto‑generates embedding when embedder is set
        registry.register(_make_skill("skill.alpha", "alphabetical operations"))
        registry.register(_make_skill("skill.beta", "beta testing utilities"))
        registry.register(_make_skill("skill.gamma", "gamma ray processing"))

        assert len(store) == 3

    def test_vector_store_increases_per_registration(self) -> None:
        """Vector store length increases by 1 after each register() with embedder."""
        from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
        from src.capabilities.discovery.vector_store import VectorStore
        from src.capabilities.discovery.embedder import SkillEmbedder
        from src.capabilities.discovery.providers.mock_provider import MockEmbeddingProvider

        registry = CapabilitySkillRegistry()
        embedder = SkillEmbedder(provider=MockEmbeddingProvider(dimensions=8), cache_enabled=False)
        registry.set_embedder(embedder)

        store = VectorStore()
        registry.set_vector_store(store)

        store_before = len(store)
        registry.register(_make_skill("single", "only one"))
        assert len(store) == store_before + 1

    def test_clear_vector_store_resets_count(self) -> None:
        """Clearing the vector store resets count to 0."""
        from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
        from src.capabilities.discovery.vector_store import VectorStore
        from src.capabilities.discovery.embedder import SkillEmbedder
        from src.capabilities.discovery.providers.mock_provider import MockEmbeddingProvider

        registry = CapabilitySkillRegistry()
        embedder = SkillEmbedder(provider=MockEmbeddingProvider(dimensions=8), cache_enabled=False)
        registry.set_embedder(embedder)

        store = VectorStore()
        registry.set_vector_store(store)

        registry.register(_make_skill("temp", "temporary"))
        assert len(store) == 1

        store.clear()
        assert len(store) == 0


class TestHotReloadE2E:
    """PHASE 3.19.7: End-to-end hot-reload: reembed → find_semantic."""

    def test_reembed_updates_vector_store_entry(self) -> None:
        """After reembed, the vector store entry is updated (same skill, no count change)."""
        from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
        from src.capabilities.discovery.vector_store import VectorStore
        from src.capabilities.discovery.embedder import SkillEmbedder
        from src.capabilities.discovery.providers.mock_provider import MockEmbeddingProvider

        registry = CapabilitySkillRegistry()
        embedder = SkillEmbedder(provider=MockEmbeddingProvider(dimensions=8), cache_enabled=False)
        registry.set_embedder(embedder)

        store = VectorStore()
        registry.set_vector_store(store)

        # register() auto‑generates embedding → already in vector store
        registry.register(_make_skill("refreshable", "initial description"))

        # Verify skill can be found
        results = registry.find_semantic("initial description", k=1)
        assert len(results) == 1
        assert results[0][0].manifest.name == "refreshable"
        initial_score = results[0][1]

        # Re-embed (no text change → score should be identical)
        registry.reembed("refreshable")
        assert len(store) == 1  # count unchanged

        results_after = registry.find_semantic("initial description", k=1)
        assert len(results_after) == 1
        assert results_after[0][1] == pytest.approx(initial_score)

    def test_reembed_all_works_across_multiple_skills(self) -> None:
        """reembed_all() updates embeddings for all registered skills."""
        from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
        from src.capabilities.discovery.vector_store import VectorStore
        from src.capabilities.discovery.embedder import SkillEmbedder
        from src.capabilities.discovery.providers.mock_provider import MockEmbeddingProvider

        registry = CapabilitySkillRegistry()
        embedder = SkillEmbedder(provider=MockEmbeddingProvider(dimensions=8), cache_enabled=False)
        registry.set_embedder(embedder)

        store = VectorStore()
        registry.set_vector_store(store)

        registry.register(_make_skill("skill.one", "first skill"))
        registry.register(_make_skill("skill.two", "second skill"))
        assert len(store) == 2

        # reembed_all should not change count
        registry.reembed_all()
        assert len(store) == 2

        # Both skills still findable
        r1 = registry.find_semantic("first skill", k=1)
        r2 = registry.find_semantic("second skill", k=1)
        assert r1[0][0].manifest.name == "skill.one"
        assert r2[0][0].manifest.name == "skill.two"

    def test_reembed_after_skill_text_changes(self) -> None:
        """Reembed after modifying skill manifest updates search results."""
        from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
        from src.capabilities.discovery.vector_store import VectorStore
        from src.capabilities.discovery.embedder import SkillEmbedder
        from src.capabilities.discovery.providers.mock_provider import MockEmbeddingProvider

        registry = CapabilitySkillRegistry()
        embedder = SkillEmbedder(provider=MockEmbeddingProvider(dimensions=8), cache_enabled=False)
        registry.set_embedder(embedder)

        store = VectorStore()
        registry.set_vector_store(store)

        skill = _make_skill("morphable", "database operations")
        registry.register(skill)

        # Search for "file" should not match well initially
        results_before = registry.find_semantic("file system operations", k=1)
        score_before = results_before[0][1] if results_before else 0.0

        # Modify skill's description to be about file operations
        skill.manifest.description = "file system and disk operations"
        registry.reembed("morphable")

        results_after = registry.find_semantic("file system operations", k=1)
        score_after = results_after[0][1] if results_after else 0.0

        # After reembed, score should be different
        assert score_after != pytest.approx(score_before, abs=1e-3)

    def test_hot_reload_preserves_registry_count(self) -> None:
        """Hot-reload (reembed) does not change skill count in registry or vector store."""
        from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
        from src.capabilities.discovery.vector_store import VectorStore
        from src.capabilities.discovery.embedder import SkillEmbedder
        from src.capabilities.discovery.providers.mock_provider import MockEmbeddingProvider

        registry = CapabilitySkillRegistry()
        embedder = SkillEmbedder(provider=MockEmbeddingProvider(dimensions=8), cache_enabled=False)
        registry.set_embedder(embedder)

        store = VectorStore()
        registry.set_vector_store(store)

        registry.register(_make_skill("persistent", "unchanging skill"))
        assert len(registry.list()) == 1
        assert len(store) == 1

        registry.reembed("persistent")
        assert len(registry.list()) == 1
        assert len(store) == 1
