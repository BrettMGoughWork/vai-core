"""Deterministic registry for storing, retrieving, listing, and searching patterns."""

from __future__ import annotations

from typing import Callable

from src.domain.patterns import PatternDefinition


class PatternRegistry:
    """In-memory registry for S3 pattern definitions.

    Populated at startup from ``config/patterns/*.yaml`` and read-only at runtime.
    All discovery methods are deterministic and side-effect free.
    """

    def __init__(self) -> None:
        self._patterns: dict[str, PatternDefinition] = {}

    def register(self, pattern: PatternDefinition) -> None:
        """Register a pattern definition.

        Raises:
            ValueError: If *pattern.pattern_id* is already registered.
        """
        pid = pattern.pattern_id
        if pid in self._patterns:
            raise ValueError(f"Pattern '{pid}' is already registered")
        self._patterns[pid] = pattern

    def get(self, pattern_id: str) -> PatternDefinition | None:
        """Return the pattern registered under *pattern_id*, or *None* if not found."""
        return self._patterns.get(pattern_id)

    def list(
        self, filter: Callable[[PatternDefinition], bool] | None = None
    ) -> list[PatternDefinition]:
        """Return all patterns, optionally filtered by *filter*."""
        if filter is None:
            return list(self._patterns.values())
        return [p for p in self._patterns.values() if filter(p)]

    def remove(self, pattern_id: str) -> None:
        """Remove a pattern from the registry.

        Raises:
            KeyError: If *pattern_id* is not registered.
        """
        if pattern_id not in self._patterns:
            raise KeyError(f"Pattern '{pattern_id}' is not registered")
        del self._patterns[pattern_id]

    def find(self, query: str) -> list[dict]:
        """Search patterns by *pattern_id* and *description*, returning scored results.

        Scoring rules:
            - +2 if *query* is a substring of the pattern_id
            - +1 if *query* is a substring of the description
            - Exclude results with score == 0
            - Sort descending by score

        Returns:
            A list of dicts with keys ``pattern_id``, ``pattern``, and ``score``.
        """
        results: list[dict] = []
        query_lower = query.lower()
        for pid, pattern in self._patterns.items():
            score = 0
            if query_lower in pid.lower():
                score += 2
            if query_lower in pattern.description.lower():
                score += 1
            if score > 0:
                results.append({
                    "pattern_id": pid,
                    "pattern": pattern,
                    "score": score,
                })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    @property
    def count(self) -> int:
        """Number of registered patterns."""
        return len(self._patterns)

    def has_pattern(self, pattern_id: str) -> bool:
        """Check whether a pattern ID is registered."""
        return pattern_id in self._patterns
