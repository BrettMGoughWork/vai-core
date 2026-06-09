"""
Embedding provider package (PHASE 3.19.1).

Factory and exports for pluggable embedding providers used by
SkillEmbedder to generate semantic embeddings for skill discovery.
"""

from __future__ import annotations

from .base import EmbeddingProvider
from .local_provider import LocalEmbeddingProvider
from .mock_provider import MockEmbeddingProvider
from .openai_provider import OpenAIEmbeddingProvider

__all__ = [
    "EmbeddingProvider",
    "LocalEmbeddingProvider",
    "MockEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "get_embedding_provider",
]


def get_embedding_provider(
    provider: str = "mock",
    model: str | None = None,
    dimensions: int = 1536,
    api_key_env: str | None = None,
) -> EmbeddingProvider:
    """Create an embedding provider from its name.

    Args:
        provider: One of ``"openai"``, ``"local"``, or ``"mock"``.
        model: Model name (required for ``"openai"``, optional for ``"local"``).
        dimensions: Embedding vector dimensionality.
        api_key_env: Name of env var holding the API key (for ``"openai"``).

    Returns:
        A concrete ``EmbeddingProvider`` instance.

    Raises:
        ValueError: If *provider* is not recognised.
    """
    name = provider.lower()
    if name == "openai":
        return OpenAIEmbeddingProvider(
            model=model or "text-embedding-3-small",
            dimensions=dimensions,
            api_key_env=api_key_env,
        )
    if name == "local":
        return LocalEmbeddingProvider(
            model=model or "all-MiniLM-L6-v2",
            dimensions=dimensions,
        )
    if name == "mock":
        return MockEmbeddingProvider(dimensions=dimensions)

    raise ValueError(f"Unknown embedding provider: {provider!r}")
