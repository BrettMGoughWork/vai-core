from __future__ import annotations

from typing import Callable

from src.capabilities.primitives.base import PrimitiveBase


class PrimitiveRegistry:
    """Deterministic registry for storing, retrieving, listing, and searching S3 primitives."""

    def __init__(self) -> None:
        self._primitives: dict[str, PrimitiveBase] = {}

    def register(self, name: str, primitive: PrimitiveBase) -> None:
        """Register a primitive under *name*.

        Raises:
            ValueError: If *name* is already registered.
        """
        if name in self._primitives:
            raise ValueError(f"Primitive '{name}' is already registered")
        self._primitives[name] = primitive

    def get(self, name: str) -> PrimitiveBase | None:
        """Return the primitive registered under *name*, or *None* if not found."""
        return self._primitives.get(name)

    def list(
        self, filter: Callable[[PrimitiveBase], bool] | None = None
    ) -> list[PrimitiveBase]:
        """Return all primitives, optionally filtered by *filter*."""
        if filter is None:
            return list(self._primitives.values())
        return [p for p in self._primitives.values() if filter(p)]

    def find(self, query: str) -> list[dict]:
        """Search primitives by *name* and *description*, returning scored results.

        Scoring rules:
            - +2 if *query* is a substring of the primitive's name
            - +1 if *query* is a substring of the primitive's description
            - Exclude results with score == 0
            - Sort descending by score

        Returns:
            A list of dicts with keys ``name``, ``primitive``, and ``score``.
        """
        results: list[dict] = []
        query_lower = query.lower()
        for name, primitive in self._primitives.items():
            score = 0
            if query_lower in name.lower():
                score += 2
            if query_lower in primitive.description.lower():
                score += 1
            if score > 0:
                results.append(
                    {
                        "name": name,
                        "primitive": primitive,
                        "score": score,
                    }
                )
        results.sort(key=lambda r: r["score"], reverse=True)
        return results