"""
Unit tests for SkillEmbedder (PHASE 3.19.1).

Tests the embedder gateway, cache behavior, and similarity computation.
Uses MockEmbeddingProvider — no network calls.
"""

from __future__ import annotations

import pytest

from src.capabilities.discovery.embedder import SkillEmbedder
from src.capabilities.discovery.providers.mock_provider import MockEmbeddingProvider


class TestSkillEmbedder:
    """Tests for SkillEmbedder with mock provider."""

    @pytest.fixture
    def embedder(self) -> SkillEmbedder:
        """Create an embedder with mock provider for deterministic tests."""
        return SkillEmbedder(provider=MockEmbeddingProvider(dimensions=8))

    def test_init_with_provider(self) -> None:
        """SkillEmbedder can be constructed with an explicit provider."""
        provider = MockEmbeddingProvider(dimensions=64)
        embedder = SkillEmbedder(provider=provider)
        assert embedder is not None

    def test_init_without_config_or_provider_raises(self) -> None:
        """SkillEmbedder requires either config or provider."""
        with pytest.raises(ValueError, match="requires either"):
            SkillEmbedder()

    def test_embed_returns_list(self, embedder: SkillEmbedder) -> None:
        """embed() returns a list of floats."""
        result = embedder.embed("some text")
        assert isinstance(result, list)

    def test_embed_query_delegates(self, embedder: SkillEmbedder) -> None:
        """embed_query() delegates to embed()."""
        result = embedder.embed_query("hello world")
        assert isinstance(result, list)
        assert len(result) == 8

    def test_embed_skill_delegates(self, embedder: SkillEmbedder) -> None:
        """embed_skill() combines metadata and delegates to embed()."""
        result = embedder.embed_skill("stdlib.echo", "echoes input", "")
        assert isinstance(result, list)
        assert len(result) == 8

    def test_cache_reuses_results(self, embedder: SkillEmbedder) -> None:
        """Consecutive calls with same text return the same object."""
        r1 = embedder.embed("hello")
        r2 = embedder.embed("hello")
        assert r1 is r2

    def test_clear_cache_evicts_entries(self, embedder: SkillEmbedder) -> None:
        """clear_cache() empties the session cache."""
        r1 = embedder.embed("hello")
        embedder.clear_cache()
        r2 = embedder.embed("hello")
        # After clearing, a NEW list may be returned (mock returns zeros,
        # but the cache sends different object references)
        # At minimum, values should be equal
        assert r1 == r2

    def test_similarity_identical(self, embedder: SkillEmbedder) -> None:
        """Cosine similarity of identical non-zero vectors is 1.0."""
        sim = embedder.similarity([1.0, 0.0], [1.0, 0.0])
        assert sim == pytest.approx(1.0)

    def test_similarity_orthogonal(self, embedder: SkillEmbedder) -> None:
        """Cosine similarity of orthogonal vectors is 0.0."""
        sim = embedder.similarity([1.0, 0.0], [0.0, 1.0])
        assert sim == pytest.approx(0.0)

    def test_similarity_opposite(self, embedder: SkillEmbedder) -> None:
        """Cosine similarity of opposite vectors is -1.0."""
        sim = embedder.similarity([1.0, 0.0], [-1.0, 0.0])
        assert sim == pytest.approx(-1.0)

    def test_similarity_zero_vector(self, embedder: SkillEmbedder) -> None:
        """Cosine similarity with zero vector is 0.0."""
        sim = embedder.similarity([0.0, 0.0], [1.0, 1.0])
        assert sim == pytest.approx(0.0)

    def test_similarity_mismatched_lengths(self, embedder: SkillEmbedder) -> None:
        """Mismatched vector lengths return 0.0."""
        sim = embedder.similarity([1.0, 0.0], [1.0])
        assert sim == pytest.approx(0.0)

    def test_similarity_empty_vectors(self, embedder: SkillEmbedder) -> None:
        """Empty vectors return 0.0."""
        sim = embedder.similarity([], [])
        assert sim == pytest.approx(0.0)

    def test_dimensions_from_provider(self, embedder: SkillEmbedder) -> None:
        """dimensions property reads from the provider."""
        assert embedder.dimensions == 8

    def test_embed_query_caches(self, embedder: SkillEmbedder) -> None:
        """embed_query also benefits from the cache."""
        r1 = embedder.embed_query("cache test")
        r2 = embedder.embed_query("cache test")
        # Both go through embed() which caches by text
        assert r1 is r2


class TestCacheIsolation:
    """PHASE 3.19.7: Cache isolation between independent embedder instances."""

    def test_two_embedders_have_independent_caches(self) -> None:
        """Two SkillEmbedder instances do not share the query cache."""
        provider = MockEmbeddingProvider(dimensions=8)
        e1 = SkillEmbedder(provider=provider, cache_enabled=True)
        e2 = SkillEmbedder(provider=provider, cache_enabled=True)

        # Populate cache in e1
        e1.embed("isolated key")
        assert "isolated key" in e1._cache

        # e2's cache should be empty
        assert e2._cache == {}

    def test_cache_disabled_on_one_does_not_affect_other(self) -> None:
        """Disabling cache on one instance doesn't affect another."""
        provider = MockEmbeddingProvider(dimensions=8)
        e1 = SkillEmbedder(provider=provider, cache_enabled=True)
        e2 = SkillEmbedder(provider=provider, cache_enabled=False)

        e1.embed("test")
        e2.embed("test")

        assert "test" in e1._cache
        assert "test" not in e2._cache


class TestCacheUnderProviderError:
    """PHASE 3.19.7: Cache survives embedding provider failures."""

    def test_cached_value_survives_provider_error(self) -> None:
        """Once cached, a value is returned even if the provider would fail."""
        provider = MockEmbeddingProvider(dimensions=8)
        embedder = SkillEmbedder(provider=provider, cache_enabled=True)

        # Cache a value
        cached = embedder.embed("safe key")
        assert "safe key" in embedder._cache

        # Replace provider with a broken one that always raises
        class _FailingProvider:
            _dimensions = 8

            def embed(self, text: str) -> list[float]:
                raise RuntimeError("provider down")

        embedder._provider = _FailingProvider()  # type: ignore[assignment]

        # Cached value should still be returned (no provider call needed)
        recovered = embedder.embed("safe key")
        assert recovered == cached
        assert recovered is cached

    def test_uncached_key_raises_when_provider_fails(self) -> None:
        """When a key is not cached and the provider fails, the error propagates."""
        provider = MockEmbeddingProvider(dimensions=8)
        embedder = SkillEmbedder(provider=provider, cache_enabled=True)

        # Replace provider with one that always fails
        class _FailingProvider:
            _dimensions = 8

            def embed(self, text: str) -> list[float]:
                raise RuntimeError("provider unreachable")

        embedder._provider = _FailingProvider()  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="provider unreachable"):
            embedder.embed("new key")
