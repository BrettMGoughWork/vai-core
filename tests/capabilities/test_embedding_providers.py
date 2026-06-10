"""
Unit tests for embedding providers (PHASE 3.19.4).

Tests the provider interface, mock provider, factory function, cache bypass,
and config-driven API key injection.
Does NOT make network calls or require external API keys.
"""

from __future__ import annotations

import pytest

from src.capabilities.discovery.embedder import SkillEmbedder
from src.capabilities.discovery.providers import get_embedding_provider
from src.capabilities.discovery.providers.base import EmbeddingProvider
from src.capabilities.discovery.providers.mock_provider import MockEmbeddingProvider
from src.capabilities.discovery.providers.openai_provider import OpenAIEmbeddingProvider
from src.capabilities.discovery.providers.local_provider import LocalEmbeddingProvider
from src.core.state.config import EmbeddingConfig


class TestMockProvider:
    """Tests for the mock (deterministic) embedding provider."""

    def test_returns_deterministic_vector(self) -> None:
        """Mock provider returns a deterministic vector (not all zeros)."""
        provider = MockEmbeddingProvider(dimensions=8)
        result = provider.embed("any text")
        assert len(result) == 8
        assert isinstance(result, list)
        assert all(isinstance(x, float) for x in result)
        # Deterministic: same input → same output
        assert result == provider.embed("any text")

    def test_different_texts_produce_different_vectors(self) -> None:
        """Different strings yield different embeddings."""
        provider = MockEmbeddingProvider(dimensions=8)
        v1 = provider.embed("hello")
        v2 = provider.embed("world")
        assert v1 != v2, "different strings must produce different vectors"

    def test_vector_is_unit_normalised(self) -> None:
        """Output vectors are unit length (within floating-point tolerance)."""
        import math
        provider = MockEmbeddingProvider(dimensions=16)
        result = provider.embed("test vector")
        norm = math.sqrt(sum(v * v for v in result))
        assert abs(norm - 1.0) < 1e-9 or norm == 0.0

    def test_dimensions_are_configurable(self) -> None:
        """Dimensions parameter is respected."""
        for dims in [8, 256, 1536]:
            provider = MockEmbeddingProvider(dimensions=dims)
            assert len(provider.embed("test")) == dims

    def test_embed_returns_float_list(self) -> None:
        """Result is a list of floats."""
        provider = MockEmbeddingProvider(dimensions=16)
        result = provider.embed("hello")
        assert isinstance(result, list)
        assert all(isinstance(x, float) for x in result)

    def test_conforms_to_protocol(self) -> None:
        """Mock provider satisfies the EmbeddingProvider protocol."""
        provider = MockEmbeddingProvider(dimensions=32)
        assert isinstance(provider, EmbeddingProvider)

    def test_empty_input(self) -> None:
        """Empty string is handled — returns zero vector."""
        provider = MockEmbeddingProvider(dimensions=64)
        result = provider.embed("")
        assert len(result) == 64
        # Empty string → all zeros (no characters to hash)
        assert result == [0.0] * 64


class TestFactory:
    """Tests for get_embedding_provider factory."""

    def test_creates_mock_provider(self) -> None:
        """Factory creates MockEmbeddingProvider for 'mock'."""
        provider = get_embedding_provider(provider="mock", dimensions=64)
        assert isinstance(provider, MockEmbeddingProvider)
        assert len(provider.embed("test")) == 64

    def test_creates_openai_provider(self) -> None:
        """Factory creates OpenAIEmbeddingProvider for 'openai'."""
        provider = get_embedding_provider(
            provider="openai", model="text-embedding-3-small", dimensions=1536
        )
        assert isinstance(provider, OpenAIEmbeddingProvider)

    def test_creates_local_provider(self) -> None:
        """Factory creates LocalEmbeddingProvider for 'local'."""
        provider = get_embedding_provider(
            provider="local", model="all-MiniLM-L6-v2", dimensions=384
        )
        assert isinstance(provider, LocalEmbeddingProvider)

    def test_unknown_provider_raises(self) -> None:
        """Factory raises ValueError for unknown provider names."""
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            get_embedding_provider(provider="nonexistent", dimensions=64)

    def test_default_dimensions_used(self) -> None:
        """Factory uses default dimensions when not specified."""
        provider = get_embedding_provider(provider="mock")
        assert len(provider.embed("test")) == 1536  # default

    def test_mock_provider_stores_dimensions(self) -> None:
        """Mock provider exposes _dimensions for SkillEmbedder."""
        provider = MockEmbeddingProvider(dimensions=512)
        assert provider._dimensions == 512


class TestLocalProvider:
    """Tests for the local embedding provider without sentence-transformers."""

    def test_conforms_to_protocol(self) -> None:
        """Local provider satisfies the EmbeddingProvider protocol."""
        provider = LocalEmbeddingProvider(
            model="all-MiniLM-L6-v2", dimensions=384
        )
        assert isinstance(provider, EmbeddingProvider)

    def test_returns_correct_dimensions(self) -> None:
        """Local provider respects the dimensions parameter."""
        provider = LocalEmbeddingProvider(
            model="all-MiniLM-L6-v2", dimensions=384
        )
        result = provider.embed("test")
        assert len(result) == 384


class TestOpenAIProvider:
    """Tests for the OpenAI provider structure (no API calls)."""

    def test_conforms_to_protocol(self) -> None:
        """OpenAI provider satisfies the EmbeddingProvider protocol."""
        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-small", dimensions=1536
        )
        assert isinstance(provider, EmbeddingProvider)

    def test_stores_model_and_dimensions(self) -> None:
        """Provider stores model name and dimensions."""
        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-small", dimensions=1536
        )
        assert provider._model == "text-embedding-3-small"
        assert provider._dimensions == 1536

    def test_api_key_env_stored(self) -> None:
        """OpenAI provider stores the api_key_env parameter."""
        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-small",
            dimensions=1536,
            api_key_env="CUSTOM_KEY_ENV",
        )
        assert provider._api_key_env == "CUSTOM_KEY_ENV"


class TestConfigDrivenProvider:
    """Tests for config-driven provider creation (PHASE 3.19.4)."""

    def test_factory_creates_openai_with_custom_api_key_env(self) -> None:
        """Factory forwards api_key_env to OpenAI provider."""
        provider = get_embedding_provider(
            provider="openai",
            model="text-embedding-3-small",
            dimensions=1536,
            api_key_env="MY_CUSTOM_KEY",
        )
        assert isinstance(provider, OpenAIEmbeddingProvider)
        assert provider._api_key_env == "MY_CUSTOM_KEY"

    def test_factory_creates_openai_without_api_key_env(self) -> None:
        """Factory creates OpenAI provider without api_key_env (defaults to OPENAI_API_KEY)."""
        provider = get_embedding_provider(
            provider="openai",
            model="text-embedding-3-small",
            dimensions=1536,
        )
        assert isinstance(provider, OpenAIEmbeddingProvider)
        assert provider._api_key_env == "OPENAI_API_KEY"

    def test_embedder_creates_provider_from_config(self) -> None:
        """SkillEmbedder uses EmbeddingConfig to create the provider."""
        config = EmbeddingConfig(
            provider="mock",
            model="mock-model",
            dimensions=128,
        )
        embedder = SkillEmbedder(config=config)
        assert isinstance(embedder._provider, MockEmbeddingProvider)
        assert embedder.dimensions == 128


class TestCacheBypass:
    """Tests for SkillEmbedder cache bypass (PHASE 3.19.4)."""

    def test_cache_enabled_by_default(self) -> None:
        """Cache is enabled by default."""
        provider = MockEmbeddingProvider(dimensions=8)
        embedder = SkillEmbedder(provider=provider)
        assert embedder._cache_enabled is True
        assert embedder._cache == {}

    def test_cache_stores_and_returns_cached_value(self) -> None:
        """With cache_enabled=True, repeated embeds return cached results."""
        provider = MockEmbeddingProvider(dimensions=8)
        embedder = SkillEmbedder(provider=provider, cache_enabled=True)

        v1 = embedder.embed("hello")
        assert "hello" in embedder._cache
        v2 = embedder.embed("hello")
        assert v1 is v2  # Same object (cached)

    def test_cache_disabled_bypasses_cache(self) -> None:
        """With cache_enabled=False, cache is never populated."""
        provider = MockEmbeddingProvider(dimensions=8)
        embedder = SkillEmbedder(provider=provider, cache_enabled=False)

        embedder.embed("hello")
        assert "hello" not in embedder._cache
        # Repeated calls still go to provider (deterministic but not cached)
        v1 = embedder.embed("hello")
        v2 = embedder.embed("hello")
        assert v1 == v2
        assert embedder._cache == {}

    def test_clear_cache_works(self) -> None:
        """clear_cache() empties the session cache."""
        provider = MockEmbeddingProvider(dimensions=8)
        embedder = SkillEmbedder(provider=provider, cache_enabled=True)

        embedder.embed("hello")
        assert len(embedder._cache) > 0
        embedder.clear_cache()
        assert embedder._cache == {}

    def test_embedder_without_config_or_provider_raises(self) -> None:
        """SkillEmbedder raises if neither config nor provider is given."""
        with pytest.raises(ValueError, match="requires either a config"):
            SkillEmbedder()


class TestConfigParseChain:
    """PHASE 3.19.7: config.yaml → EmbeddingConfig parse chain."""

    def test_from_yaml_with_openai_config(self) -> None:
        """Parse a YAML-style dict with openai provider."""
        data = {
            "provider": "openai",
            "model": "text-embedding-3-large",
            "dimensions": 3072,
            "api_key_env": "CUSTOM_KEY",
        }
        config = EmbeddingConfig.from_yaml(data)
        assert config is not None
        assert config.provider == "openai"
        assert config.model == "text-embedding-3-large"
        assert config.dimensions == 3072
        assert config.api_key_env == "CUSTOM_KEY"

    def test_from_yaml_with_local_config(self) -> None:
        """Parse a YAML-style dict with local provider."""
        data = {
            "provider": "local",
            "model": "all-MiniLM-L6-v2",
            "dimensions": 384,
        }
        config = EmbeddingConfig.from_yaml(data)
        assert config is not None
        assert config.provider == "local"
        assert config.model == "all-MiniLM-L6-v2"
        assert config.dimensions == 384
        assert config.api_key_env is None

    def test_from_yaml_with_mock_config(self) -> None:
        """Parse a YAML-style dict with mock provider."""
        data = {
            "provider": "mock",
            "model": "mock-model",
            "dimensions": 64,
        }
        config = EmbeddingConfig.from_yaml(data)
        assert config is not None
        assert config.provider == "mock"
        assert config.dimensions == 64

    def test_from_yaml_none_returns_none(self) -> None:
        """from_yaml(None) returns None."""
        assert EmbeddingConfig.from_yaml(None) is None

    def test_from_yaml_empty_dict_returns_none(self) -> None:
        """from_yaml({}) returns None."""
        assert EmbeddingConfig.from_yaml({}) is None

    def test_from_yaml_partial_uses_defaults(self) -> None:
        """Partial config uses built-in defaults for missing keys."""
        config = EmbeddingConfig.from_yaml({"provider": "local"})
        assert config is not None
        assert config.provider == "local"
        assert config.model == "text-embedding-3-small"  # default
        assert config.dimensions == 1536  # default
        assert config.api_key_env is None  # default

    def test_from_yaml_defaults_when_missing_dimensions(self) -> None:
        """Dimensions default to 1536 when not specified."""
        config = EmbeddingConfig.from_yaml({"provider": "openai"})
        assert config is not None
        assert config.dimensions == 1536

    def test_from_yaml_handles_api_key_env_none(self) -> None:
        """api_key_env defaults to None when not provided."""
        config = EmbeddingConfig.from_yaml({"provider": "mock", "dimensions": 256})
        assert config is not None
        assert config.api_key_env is None

    def test_embedder_from_config_chain(self) -> None:
        """Full chain: from_yaml → SkillEmbedder creates correct provider."""
        yaml_data = {"provider": "mock", "model": "mock-v2", "dimensions": 128}
        config = EmbeddingConfig.from_yaml(yaml_data)
        assert config is not None

        embedder = SkillEmbedder(config=config)
        assert isinstance(embedder._provider, MockEmbeddingProvider)
        assert embedder.dimensions == 128


class TestInvalidConfigHandling:
    """PHASE 3.19.7: Invalid EmbeddingConfig error handling."""

    def test_unknown_provider_in_config_raises_at_embedder(self) -> None:
        """Unknown provider name raises when SkillEmbedder creates the provider."""
        config = EmbeddingConfig(
            provider="nonexistent-provider",
            model="some-model",
            dimensions=768,
        )
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            SkillEmbedder(config=config)

    def test_from_yaml_with_unknown_provider_creates_config(self) -> None:
        """from_yaml accepts any provider string (validation deferred to factory)."""
        data = {"provider": "custom-future-provider", "dimensions": 512}
        config = EmbeddingConfig.from_yaml(data)
        assert config is not None
        assert config.provider == "custom-future-provider"

    def test_config_with_zero_dimensions(self) -> None:
        """Zero dimensions is allowed at config level (provider validates)."""
        config = EmbeddingConfig(provider="mock", dimensions=0)
        assert config.dimensions == 0
        # mock provider accepts any dimension
        embedder = SkillEmbedder(config=config)
        assert embedder.dimensions == 0
        result = embedder.embed("test")
        assert result == []  # 0-dimension vector is empty

    def test_config_with_negative_dimensions(self) -> None:
        """Negative dimensions is allowed at config level (provider may reject)."""
        config = EmbeddingConfig(provider="mock", dimensions=-1)
        assert config.dimensions == -1


class TestRealProviderEmbed:
    """PHASE 3.19.7: Real provider embed() integration tests.

    These tests call actual embedding providers and are skipped
    when no API key or local model is available.
    """

    @pytest.mark.integration
    def test_openai_embed_call(self) -> None:
        """Real OpenAI embed() call — requires OPENAI_API_KEY env var."""
        import os
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")

        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-small",
            dimensions=1536,
        )
        result = provider.embed("test vector for semantic search")
        assert isinstance(result, list)
        assert len(result) == 1536
        assert all(isinstance(x, float) for x in result)
        # Non-trivial: not all zeros
        assert any(abs(x) > 1e-6 for x in result)

    @pytest.mark.integration
    def test_openai_deterministic_same_input(self) -> None:
        """Same input to OpenAI produces near-identical embeddings."""
        import os
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")

        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-small",
            dimensions=1536,
        )
        r1 = provider.embed("consistent test input")
        r2 = provider.embed("consistent test input")
        # OpenAI embeddings are deterministic for the same input
        assert len(r1) == len(r2)
        # Cosine similarity between runs should be > 0.99
        dot = sum(a * b for a, b in zip(r1, r2))
        norm1 = sum(a * a for a in r1) ** 0.5
        norm2 = sum(b * b for b in r2) ** 0.5
        similarity = dot / (norm1 * norm2) if norm1 > 0 and norm2 > 0 else 0.0
        assert similarity > 0.99, f"Expected near-identical embeddings, got cos={similarity:.4f}"

    @pytest.mark.integration
    def test_local_embed_call(self) -> None:
        """Real local embed() call via sentence-transformers."""
        import importlib
        try:
            importlib.import_module("sentence_transformers")
        except ImportError:
            pytest.skip("sentence-transformers not installed")

        provider = LocalEmbeddingProvider(
            model="all-MiniLM-L6-v2",
            dimensions=384,
        )
        result = provider.embed("test semantic search query")
        assert isinstance(result, list)
        assert len(result) == 384
        assert all(isinstance(x, float) for x in result)
        assert any(abs(x) > 1e-6 for x in result)
