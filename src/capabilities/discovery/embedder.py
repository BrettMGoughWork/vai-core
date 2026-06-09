"""
Skill embedder (Phase 3.19.1).

Generates vector embeddings for skill manifests to enable
semantic search during skill discovery.

Uses the configured embedding provider (OpenAI, local, or mock)
loaded from config.yaml.  Maintains a per-session query cache.
"""

from __future__ import annotations

from typing import Dict, List

from src.capabilities.discovery.providers import get_embedding_provider
from src.capabilities.discovery.providers.base import EmbeddingProvider
from src.core.state.config import EmbeddingConfig


class SkillEmbedder:
    """
    Generates and manages embeddings for skill manifests.

    Embeddings are ONLY used for discovery fallback — when the LLM
    fails to name a capability.  LLM-chosen skills always take precedence.
    """

    def __init__(
        self,
        config: EmbeddingConfig | None = None,
        provider: EmbeddingProvider | None = None,
        cache_enabled: bool = True,
    ) -> None:
        """Initialise the embedder.

        Args:
            config: ``EmbeddingConfig`` from the runtime.  If provided and
                    *provider* is ``None``, the factory creates a provider.
            provider: Direct provider injection (for tests).  Overrides config.
            cache_enabled: When ``False``, the per-session query cache is
                           bypassed.  Use for deterministic unit tests.
        """
        self._cache: Dict[str, List[float]] = {}
        self._cache_enabled = cache_enabled

        if provider is not None:
            self._provider = provider
        elif config is not None:
            self._provider = get_embedding_provider(
                provider=config.provider,
                model=config.model,
                dimensions=config.dimensions,
                api_key_env=config.api_key_env,
            )
        else:
            raise ValueError(
                "SkillEmbedder requires either a config or an explicit provider"
            )

    @property
    def dimensions(self) -> int:
        """Return the embedding vector dimension."""
        return self._provider._dimensions  # type: ignore[attr-defined]

    def embed(self, text: str) -> List[float]:
        """Generate an embedding vector for *text*, using the session cache.

        When ``cache_enabled`` is ``False``, the cache is bypassed entirely
        and every call delegates to the provider — useful for deterministic
        unit tests that use ``_simple_embedding_fn``.
        """
        if self._cache_enabled and text in self._cache:
            return self._cache[text]

        vector = self._provider.embed(text)
        if self._cache_enabled:
            self._cache[text] = vector
        return vector

    def embed_skill(
        self, name: str, description: str, body: str = ""
    ) -> List[float]:
        """Generate an embedding for a skill by combining metadata."""
        combined = f"{name}: {description}\n{body}"
        return self.embed(combined)

    def embed_query(self, query: str) -> List[float]:
        """Generate an embedding for a discovery query."""
        return self.embed(query)

    def similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two embedding vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def clear_cache(self) -> None:
        """Clear the per-session query cache."""
        self._cache.clear()
