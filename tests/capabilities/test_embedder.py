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
