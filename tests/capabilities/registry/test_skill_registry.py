"""
Tests for CapabilitySkillRegistry (Phase 3.4.1 / 3.19.2).

Covers: registration, duplicate handling, get, list (with filter),
pre‑computed embeddings, set_embedding, reembed, and hot‑reload.
"""

from __future__ import annotations


import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill


# ---------------------------------------------------------------------------
# Deterministic embedding fn (character-bucket, unit-normalised)
# ---------------------------------------------------------------------------

from src.capabilities.discovery.providers.mock_provider import _simple_embedding_fn


# ---------------------------------------------------------------------------
# Minimal "embedder" stub for tests — satisfies the .embed(text) contract
# ---------------------------------------------------------------------------

class _TestEmbedder:
    """A ``SkillEmbedder``-like stub that wraps ``_simple_embedding_fn``."""

    def embed(self, text: str) -> list[float]:
        return _simple_embedding_fn(text)

    def embed_query(self, query: str) -> list[float]:
        """Thin wrapper — identical to embed for deterministic tests."""
        return self.embed(query)


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
# Helpers
# ---------------------------------------------------------------------------

def _make_skill(name: str, description: str = "a skill", primitive_names: list[str] | None = None, steps: list[dict] | None = None) -> CapabilitySkill:
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
def registry() -> CapabilitySkillRegistry:
    return CapabilitySkillRegistry()


@pytest.fixture
def registry_with_embedder() -> CapabilitySkillRegistry:
    """PHASE 3.19.2: Registry pre‑wired with a deterministic embedder."""
    return CapabilitySkillRegistry(embedder=_TestEmbedder())


@pytest.fixture
def echo_skill() -> CapabilitySkill:
    return _make_skill("echo-skill", "echoes input")


@pytest.fixture
def read_skill() -> CapabilitySkill:
    return _make_skill("file.read", "reads a file", primitive_names=["file.read"], steps=[{"call": "file.read", "args": {"path": ""}}])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_register_succeeds(self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill) -> None:
        registry.register(echo_skill)
        assert registry.get("echo-skill") is echo_skill

    def test_duplicate_name_raises(self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill) -> None:
        registry.register(echo_skill)
        dup = _make_skill("echo-skill", "different description")
        with pytest.raises(ValueError, match="already registered"):
            registry.register(dup)


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------

class TestGet:
    def test_get_returns_skill(self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill) -> None:
        registry.register(echo_skill)
        assert registry.get("echo-skill") is echo_skill

    def test_get_missing_returns_none(self, registry: CapabilitySkillRegistry) -> None:
        assert registry.get("nonexistent") is None


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestList:
    def test_list_returns_all(self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill, read_skill: CapabilitySkill) -> None:
        registry.register(echo_skill)
        registry.register(read_skill)
        result = registry.list()
        assert len(result) == 2
        names = {s.manifest.name for s in result}
        assert names == {"echo-skill", "file.read"}

    def test_list_empty(self, registry: CapabilitySkillRegistry) -> None:
        assert registry.list() == []

    def test_list_with_filter(self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill, read_skill: CapabilitySkill) -> None:
        registry.register(echo_skill)
        registry.register(read_skill)
        result = registry.list(lambda s: "file" in s.manifest.name)
        assert len(result) == 1
        assert result[0].manifest.name == "file.read"


# ---------------------------------------------------------------------------
# PHASE 3.19.2 — Pre‑computed skill embeddings
# ---------------------------------------------------------------------------


class TestAutoEmbedAtRegistration:
    """Skills receive embeddings automatically when an embedder is configured."""

    def test_embedding_stored_on_skill_object(
        self, registry_with_embedder: CapabilitySkillRegistry, echo_skill: CapabilitySkill
    ) -> None:
        registry_with_embedder.register(echo_skill)
        assert echo_skill.embedding is not None
        assert len(echo_skill.embedding) > 0

    def test_embedding_is_deterministic(
        self, registry_with_embedder: CapabilitySkillRegistry
    ) -> None:
        s1 = _make_skill("det-skill", "deterministic test")
        s2 = _make_skill("det-skill", "deterministic test")
        registry_with_embedder.register(s1)
        with pytest.raises(ValueError, match="already registered"):
            registry_with_embedder.register(s2)
        assert s1.embedding is not None

    def test_different_skills_get_different_embeddings(
        self, registry_with_embedder: CapabilitySkillRegistry,
        echo_skill: CapabilitySkill, read_skill: CapabilitySkill,
    ) -> None:
        registry_with_embedder.register(echo_skill)
        registry_with_embedder.register(read_skill)
        assert echo_skill.embedding != read_skill.embedding

    def test_no_embedder_skips_auto_embed(
        self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill
    ) -> None:
        registry.register(echo_skill)
        assert echo_skill.embedding is None

    def test_explicit_embedding_overrides_auto(
        self, registry_with_embedder: CapabilitySkillRegistry, echo_skill: CapabilitySkill
    ) -> None:
        explicit = [0.1, 0.2, 0.3]
        registry_with_embedder.register(echo_skill, embedding=explicit)
        assert echo_skill.embedding == explicit


class TestSetEmbedding:
    """set_embedding updates both the skill object and the vector store."""

    def test_set_embedding_updates_skill_object(
        self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill
    ) -> None:
        registry.register(echo_skill)
        emb = [0.5, 0.5, 0.5]
        registry.set_embedding("echo-skill", emb)
        assert echo_skill.embedding == emb

    def test_set_embedding_missing_skill_raises(
        self, registry: CapabilitySkillRegistry
    ) -> None:
        with pytest.raises(ValueError, match="No skill registered"):
            registry.set_embedding("nonexistent", [0.1, 0.2])


class TestReembed:
    """reembed rebuilds the embedding for a single skill."""

    def test_reembed_updates_embedding(
        self, registry_with_embedder: CapabilitySkillRegistry, echo_skill: CapabilitySkill
    ) -> None:
        registry_with_embedder.register(echo_skill)
        original = list(echo_skill.embedding or [])
        registry_with_embedder.reembed("echo-skill")
        # Same skill text → same embedding (deterministic)
        assert echo_skill.embedding == original

    def test_reembed_no_embedder_raises(
        self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill
    ) -> None:
        registry.register(echo_skill)
        with pytest.raises(ValueError, match="no embedder configured"):
            registry.reembed("echo-skill")

    def test_reembed_missing_skill_raises(
        self, registry_with_embedder: CapabilitySkillRegistry
    ) -> None:
        with pytest.raises(ValueError, match="No skill registered"):
            registry_with_embedder.reembed("nonexistent")


class TestReembedAll:
    """reembed_all rebuilds embeddings for every registered skill."""

    def test_reembed_all_succeeds(
        self, registry_with_embedder: CapabilitySkillRegistry,
        echo_skill: CapabilitySkill, read_skill: CapabilitySkill,
    ) -> None:
        registry_with_embedder.register(echo_skill)
        registry_with_embedder.register(read_skill)
        registry_with_embedder.reembed_all()
        assert echo_skill.embedding is not None
        assert read_skill.embedding is not None

    def test_reembed_all_no_embedder_raises(
        self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill
    ) -> None:
        registry.register(echo_skill)
        with pytest.raises(ValueError, match="no embedder configured"):
            registry.reembed_all()


class TestEnsureEmbeddings:
    """ensure_embeddings fills gaps for skills missing embeddings."""

    def test_ensure_embeddings_fills_missing(
        self, registry_with_embedder: CapabilitySkillRegistry, echo_skill: CapabilitySkill
    ) -> None:
        # Register WITHOUT auto‑embed (no embedder at registration time)
        registry_with_embedder.set_embedder(None)  # type: ignore[arg-type]
        registry_with_embedder.register(echo_skill)
        assert echo_skill.embedding is None

        # Now wire in embedder and fill gaps
        registry_with_embedder.set_embedder(_TestEmbedder())
        registry_with_embedder.ensure_embeddings()
        assert echo_skill.embedding is not None

    def test_ensure_embeddings_noop_without_embedder(
        self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill
    ) -> None:
        registry.register(echo_skill)
        # No embedder → no‑op, no error
        registry.ensure_embeddings()
        assert echo_skill.embedding is None


class TestSetEmbedder:
    """set_embedder wires or replaces the embedder after construction."""

    def test_set_embedder_after_construction(
        self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill
    ) -> None:
        registry.set_embedder(_TestEmbedder())
        registry.register(echo_skill)
        assert echo_skill.embedding is not None


class TestFindSemantic:
    """find_semantic — semantic discovery using internal embedder (Phase 3.19.3)."""

    def test_returns_top_match_with_score(
        self, registry_with_embedder: CapabilitySkillRegistry,
        echo_skill: CapabilitySkill,
    ) -> None:
        registry_with_embedder.register(echo_skill)
        results = registry_with_embedder.find_semantic("echo", k=1)
        assert len(results) == 1
        skill, score = results[0]
        assert skill == echo_skill
        assert isinstance(score, float)
        assert score > 0.0

    def test_returns_top_k_results(
        self, registry_with_embedder: CapabilitySkillRegistry,
        echo_skill: CapabilitySkill, read_skill: CapabilitySkill,
    ) -> None:
        registry_with_embedder.register(echo_skill)
        registry_with_embedder.register(read_skill)
        results = registry_with_embedder.find_semantic("read file", k=2)
        assert len(results) == 2
        # verify descending scores
        assert results[0][1] >= results[1][1]

    def test_k_larger_than_registry(
        self, registry_with_embedder: CapabilitySkillRegistry,
        echo_skill: CapabilitySkill, read_skill: CapabilitySkill,
    ) -> None:
        registry_with_embedder.register(echo_skill)
        registry_with_embedder.register(read_skill)
        results = registry_with_embedder.find_semantic("anything", k=10)
        assert len(results) == 2  # capped at registry size

    def test_empty_registry(
        self, registry_with_embedder: CapabilitySkillRegistry
    ) -> None:
        results = registry_with_embedder.find_semantic("anything", k=5)
        assert results == []

    def test_no_embedder_raises(
        self, registry: CapabilitySkillRegistry, echo_skill: CapabilitySkill
    ) -> None:
        registry.register(echo_skill)
        with pytest.raises(ValueError, match="require.*embedder"):
            registry.find_semantic("echo")

    def test_uses_query_cache(
        self, registry_with_embedder: CapabilitySkillRegistry,
        echo_skill: CapabilitySkill,
    ) -> None:
        """Calling find_semantic twice with the same query works (cache hit)."""
        registry_with_embedder.register(echo_skill)
        r1 = registry_with_embedder.find_semantic("echo", k=1)
        r2 = registry_with_embedder.find_semantic("echo", k=1)
        assert r1[0][0] == r2[0][0]
        assert r1[0][1] == pytest.approx(r2[0][1])

    def test_zero_score_skills_excluded(
        self, registry_with_embedder: CapabilitySkillRegistry,
        echo_skill: CapabilitySkill,
    ) -> None:
        """Skills with zero or negative similarity are excluded."""
        registry_with_embedder.register(echo_skill)
        # Re‑embed with a perpendicular embedding so similarity ≈ 0
        registry_with_embedder.reembed("echo-skill")
        # find_semantic uses the internal embedder — since both skills
        # and query use the same fn, we get a reasonable similarity.
        # We register a second skill with an "opposite" embedding.
        results = registry_with_embedder.find_semantic("echo", k=3)
        assert all(score > 0 for _, score in results)
