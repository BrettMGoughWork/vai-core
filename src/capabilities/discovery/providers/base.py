"""
Embedding provider protocol (PHASE 3.19.1).

Defines the pluggable interface that all embedding backends
must implement.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for pluggable embedding backends.

    All providers MUST:
    - Accept a single text string
    - Return a ``list[float]`` of the configured dimension
    - Never alter or rewrite the input text
    """

    def embed(self, text: str) -> list[float]:
        """Return a semantic embedding vector for *text*."""
        ...
