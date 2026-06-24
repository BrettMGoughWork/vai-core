"""
Deterministic registry for storing, retrieving, listing, and searching councils.

Follows the same pattern as ``PatternRegistry`` in
``src.capabilities.patterns.pattern_registry``.
"""

from __future__ import annotations

from typing import Callable

from src.domain.council import CouncilDefinition


class CouncilRegistry:
    """In-memory registry for council definitions.

    Populated at startup from ``config/councils/*.yaml`` and read-only at runtime.
    All discovery methods are deterministic and side-effect free.
    """

    def __init__(self) -> None:
        self._councils: dict[str, CouncilDefinition] = {}

    def register(self, council: CouncilDefinition) -> None:
        """Register a council definition.

        Raises:
            ValueError: If *council.council_id* is already registered.
        """
        cid = council.council_id
        if cid in self._councils:
            raise ValueError(f"Council '{cid}' is already registered")
        self._councils[cid] = council

    def get(self, council_id: str) -> CouncilDefinition | None:
        """Return the council registered under *council_id*, or *None* if not found."""
        return self._councils.get(council_id)

    def list(
        self, filter: Callable[[CouncilDefinition], bool] | None = None
    ) -> list[CouncilDefinition]:
        """Return all councils, optionally filtered by *filter*."""
        if filter is None:
            return list(self._councils.values())
        return [c for c in self._councils.values() if filter(c)]

    def remove(self, council_id: str) -> None:
        """Remove a council from the registry.

        Raises:
            KeyError: If *council_id* is not registered.
        """
        if council_id not in self._councils:
            raise KeyError(f"Council '{council_id}' is not registered")
        del self._councils[council_id]

    def find(self, query: str) -> list[dict]:
        """Search councils by *council_id* and *description*, returning scored results.

        Scoring rules:
            - +2 if *query* is a substring of the council_id
            - +1 if *query* is a substring of the description
            - Exclude results with score == 0
            - Sort descending by score

        Returns:
            A list of dicts with keys ``council_id``, ``council``, and ``score``.
        """
        results: list[dict] = []
        query_lower = query.lower()
        for cid, council in self._councils.items():
            score = 0
            if query_lower in cid.lower():
                score += 2
            if query_lower in council.description.lower():
                score += 1
            if score > 0:
                results.append({
                    "council_id": cid,
                    "council": council,
                    "score": score,
                })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    @property
    def count(self) -> int:
        """Number of registered councils."""
        return len(self._councils)

    def has_council(self, council_id: str) -> bool:
        """Check whether a council ID is registered."""
        return council_id in self._councils
