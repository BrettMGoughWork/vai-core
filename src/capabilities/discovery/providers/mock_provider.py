"""
Mock embedding provider (PHASE 3.19.1 / 3.19.4).

Returns deterministic, text-dependent vectors for testing using the
canonical ``_simple_embedding_fn`` (character-bucket hash, unit-normalised).
Not semantic — only useful for deterministic unit tests that must
never make network calls.
"""

from __future__ import annotations

import math


def _simple_embedding_fn(text: str, dimensions: int = 8) -> list[float]:
    """Deterministic embedding: character-bucket hash, unit-normalised.

    This is the canonical implementation shared by MockEmbeddingProvider.
    Test files that previously duplicated this should import or call
    ``MockEmbeddingProvider._simple_embedding_fn`` instead.
    """
    if dimensions < 0:
        raise ValueError(f"dimensions must be non-negative, got {dimensions}")
    if dimensions == 0:
        return []
    vec = [0.0] * dimensions
    for ch in text:
        idx = ord(ch) % dimensions
        vec[idx] += 1.0
    magnitude = math.sqrt(sum(v * v for v in vec))
    if magnitude > 0:
        vec = [v / magnitude for v in vec]
    return vec


class MockEmbeddingProvider:
    """Mock provider: deterministic, text-dependent vectors.

    Uses ``_simple_embedding_fn`` so that different texts produce
    different normalised vectors, enabling similarity comparisons
    in unit tests without network calls.
    """

    def __init__(self, dimensions: int = 8) -> None:
        self._dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        """Return a deterministic embedding vector for *text*."""
        return _simple_embedding_fn(text, self._dimensions)
