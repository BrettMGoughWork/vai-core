"""Search provider protocol and result type (PHASE 3.13.1).

Every search provider MUST implement the ``SearchProvider`` protocol.
Provider identity and API keys are NEVER exposed to the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SearchProviderError(Exception):
    """Raised when a search provider encounters an unrecoverable error.

    This is the standard exception for all provider‑level failures:
    network errors, API errors, configuration errors, etc.
    """


@dataclass
class SearchResult:
    """Normalised search result in the standard S3 schema."""

    title: str
    """Concise title of the result."""

    url: str
    """Full URL to the result."""

    snippet: str
    """Short summary, NOT full content."""


class SearchProvider(Protocol):
    """Protocol that every search provider must implement.

    Providers perform NO heuristics, NO ranking, NO fallback logic,
    and NO query rewriting.  They return normalised ``SearchResult``
    objects directly.
    """

    name: str
    """Canonical provider name (e.g. 'tavily', 'duckduckgo')."""

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Execute a search and return normalised results.

        Args:
            query: The raw search query string.
            max_results: Maximum number of results to return.

        Returns:
            A list of normalised ``SearchResult`` objects.

        Raises:
            SearchProviderError: On network, API, or configuration errors.
        """
        ...
