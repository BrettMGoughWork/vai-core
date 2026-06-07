"""Embedding-based primitive discovery — generates embeddings and performs cosine-similarity search over the registry."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from src.capabilities.primitives.base import PrimitiveBase
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two embedding vectors."""
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    return dot / (norm1 * norm2) if norm1 and norm2 else 0.0


def build_primitive_embedding(primitive: PrimitiveBase, context: Dict[str, Any]) -> List[float]:
    """Build an embedding vector for *primitive* using the embedding function
    supplied in *context*.

    The embedding text is constructed from the primitive's ``name``,
    ``description``, and the docstring of its ``execute`` method.

    Raises:
        ValueError: If ``embedding_fn`` is missing from *context*.
    """
    embedding_fn = context.get("embedding_fn")
    if embedding_fn is None:
        raise ValueError("missing embedding_fn")

    execute_doc = (primitive.execute.__doc__ or "").strip()
    text = f"{primitive.name}\n{primitive.description}\n{execute_doc}"

    return embedding_fn(text)


def discover_primitives(
    query: str,
    registry: PrimitiveRegistry,
    context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Discover primitives matching *query* via cosine-similarity search.

    1. Generates an embedding for *query* using ``embedding_fn`` from *context*.
    2. For each primitive in *registry*, builds its embedding and computes
       cosine similarity against the query embedding.
    3. Returns results sorted descending by similarity, excluding scores ≤ 0.
    """
    embedding_fn = context.get("embedding_fn")
    if embedding_fn is None:
        raise ValueError("missing embedding_fn")

    query_vector = embedding_fn(query)

    results: List[Dict[str, Any]] = []
    for primitive in registry.list():
        primitive_vector = build_primitive_embedding(primitive, context)
        similarity = _cosine_similarity(query_vector, primitive_vector)
        if similarity > 0:
            results.append(
                {
                    "name": primitive.name,
                    "primitive": primitive,
                    "score": similarity,
                }
            )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results
