"""
Minimal in-memory vector store for skill-discovery fallback (Phase 3.19.1).

Uses numpy for cosine-similarity search.  No FAISS dependency —
the spec permits HNSW or numpy-based implementations.

Embeddings are ONLY used when the LLM fails to name a capability.
LLM-chosen skills always take precedence.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

import numpy as np


class VectorStore:
    """In-memory vector store with cosine-similarity search."""

    def __init__(self) -> None:
        self._vectors: List[np.ndarray] = []
        self._metadata: List[Dict[str, Any]] = []

    def add(self, embedding: List[float], metadata: Dict[str, Any]) -> None:
        """Insert a vector with associated metadata."""
        vec = np.array(embedding, dtype=np.float64)
        # Normalise on insert so search doesn't recompute
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        self._vectors.append(vec)
        self._metadata.append(metadata)

    def search(
        self, query_embedding: List[float], k: int = 1
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Return the top-*k* results as (metadata, similarity_score) tuples.

        Results are sorted by descending cosine similarity (0..1).
        Returns an empty list when the store is empty.
        """
        if not self._vectors:
            return []

        query_vec = np.array(query_embedding, dtype=np.float64)
        q_norm = float(np.linalg.norm(query_vec))
        if q_norm > 0:
            query_vec = query_vec / q_norm

        # Stack all stored vectors into a matrix and compute cosine similarities
        matrix = np.stack(self._vectors)  # (N, D)
        scores = np.dot(matrix, query_vec)  # (N,)  — already unit-length

        # Top-k by descending score
        top_indices = int(min(k, len(scores)))
        if top_indices <= 0:
            return []

        # NumPy doesn't have top-k for small N, use argsort
        sorted_indices = np.argsort(scores)[::-1][:top_indices]

        results: List[Tuple[Dict[str, Any], float]] = []
        for idx in sorted_indices:
            score = float(scores[idx])
            results.append((self._metadata[int(idx)], score))

        return results

    def __len__(self) -> int:
        return len(self._vectors)

    def update(self, name: str, new_embedding: list[float]) -> None:
        """Replace an existing vector entry identified by metadata ``"name"``.

        Used during hot‑reload to update a single skill's embedding without
        rebuilding the entire index.

        Raises:
            ValueError: If no entry with the given *name* exists.
        """
        for i, meta in enumerate(self._metadata):
            if meta.get("name") == name:
                vec = np.array(new_embedding, dtype=np.float64)
                norm = float(np.linalg.norm(vec))
                if norm > 0:
                    vec = vec / norm
                self._vectors[i] = vec
                return
        raise ValueError(f"No vector entry for name {name!r}")

    def clear(self) -> None:
        """Remove all stored vectors."""
        self._vectors.clear()
        self._metadata.clear()
