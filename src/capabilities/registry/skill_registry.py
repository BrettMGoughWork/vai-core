"""
Skill registry (Phase 3.4.1 / 3.19.1).

Deterministic registry for storing, retrieving, listing, and semantically
discovering S3 ``CapabilitySkill`` objects via embeddings.

PHASE 3.19.1: Supports pre-computed skill embeddings to avoid
re-embedding every skill on every discovery query.  Optionally uses a
VectorStore for O(log N) rather than O(N) similarity search.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Callable, List, Tuple

from src.capabilities.registry.skill_embeddings import _build_skill_text

if TYPE_CHECKING:
    from src.capabilities.discovery.embedder import SkillEmbedder
    from src.capabilities.discovery.vector_store import VectorStore
    from src.capabilities.skills.skill import CapabilitySkill


class CapabilitySkillRegistry:
    """Deterministic registry for S3 CapabilitySkill objects.

    PHASE 3.19.2: Accepts a ``SkillEmbedder`` so embeddings are
    pre-computed at registration time and stored on the skill objects.
    """

    def __init__(self, embedder: SkillEmbedder | None = None) -> None:
        self._skills: dict[str, CapabilitySkill] = {}
        self._embeddings: dict[str, list[float]] = {}
        self._vector_store: VectorStore | None = None
        self._embedder: SkillEmbedder | None = embedder

    # ── Embedder management ──────────────────────────────────────────

    def set_embedder(self, embedder: SkillEmbedder) -> None:
        """Set the ``SkillEmbedder`` used for auto‑embedding at registration time.

        Does **not** retroactively embed already‑registered skills.
        Call ``reembed_all()`` if that is desired.
        """
        self._embedder = embedder

    def set_vector_store(self, store: "VectorStore") -> None:
        """Attach a ``VectorStore`` for fast similarity search.

        Call *after* all skills are registered to rebuild the index.
        """
        self._vector_store = store
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """Rebuild the vector-store index from pre-computed embeddings."""
        if self._vector_store is None:
            return
        self._vector_store.clear()
        for name, emb in self._embeddings.items():
            self._vector_store.add(emb, {"name": name})

    # ── Registration ─────────────────────────────────────────────────

    def register(
        self,
        skill: "CapabilitySkill",
        embedding: list[float] | None = None,
    ) -> None:
        """Register a skill, optionally with a pre-computed embedding.

        The key is ``skill.manifest.name``.

        **PHASE 3.19.2**: If an embedder is configured and *embedding*
        is ``None``, the embedding is auto‑generated at registration
        time, stored on ``skill.embedding``, and inserted into the
        vector store (if one is attached).

        Raises:
            ValueError: If a skill with the same name is already registered.
        """
        name = skill.manifest.name
        if name in self._skills:
            raise ValueError(f"Skill '{name}' is already registered")

        self._skills[name] = skill

        # Auto‑generate embedding if embedder is available (3.19.2)
        if embedding is None and self._embedder is not None:
            text = _build_skill_text(skill)
            embedding = self._embedder.embed(text)

        if embedding is not None:
            self._embeddings[name] = embedding
            skill.embedding = embedding
            self._add_to_vector_store(name, embedding)

    def _add_to_vector_store(self, name: str, embedding: list[float]) -> None:
        """Insert *embedding* into the vector store if one is attached."""
        if self._vector_store is not None:
            self._vector_store.add(embedding, {"name": name})

    def _update_vector_store(self, name: str, embedding: list[float]) -> None:
        """Update an existing vector-store entry for *name* (hot‑reload).

        If the entry does not exist yet, falls back to ``_add_to_vector_store``.
        """
        if self._vector_store is None:
            return
        try:
            self._vector_store.update(name, embedding)
        except ValueError:
            self._vector_store.add(embedding, {"name": name})

    def get(self, name: str) -> "CapabilitySkill | None":
        """Return the skill registered under *name*, or ``None`` if not found."""
        return self._skills.get(name)

    def list(
        self, filter: Callable[["CapabilitySkill"], bool] | None = None
    ) -> list["CapabilitySkill"]:
        """Return all skills, optionally filtered by *filter*."""
        if filter is None:
            return list(self._skills.values())
        return [s for s in self._skills.values() if filter(s)]

    def find(
        self,
        query: str,
        context: dict,
        top_k: int = 10,
    ) -> list[dict]:
        """Semantic discovery via embeddings.

        Uses the ``VectorStore`` when attached (fast path), otherwise
        iterates all registered skills linearly.  Pre-computed skill
        embeddings are preferred over on-the-fly re-embedding.

        Args:
            query: Natural-language description of the desired capability.
            context: Must contain an ``"embedding_fn"`` key whose value is a
                     callable ``(str) -> list[float]``.
            top_k: Maximum number of results to return (default 10).

        Returns:
            A list of match dicts (``name``, ``skill``, ``score``) sorted
            descending by cosine similarity.  Zero‑score matches are excluded.

        Raises:
            ValueError: If ``"embedding_fn"`` is missing from *context*.
        """
        embedding_fn = context.get("embedding_fn")
        if embedding_fn is None:
            raise ValueError("missing embedding_fn")

        query_embedding = embedding_fn(query)

        # Fast path: vector store
        if self._vector_store is not None and len(self._vector_store) > 0:
            raw_results = self._vector_store.search(query_embedding, k=top_k)
            matches: list[dict] = []
            for meta, score in raw_results:
                name = meta["name"]
                if name in self._skills:
                    matches.append({
                        "name": name,
                        "skill": self._skills[name],
                        "score": score,
                    })
            return matches

        # Slow path: linear scan
        matches = []
        for name, skill in self._skills.items():
            # Prefer pre-computed embedding (PHASE 3.19.1)
            if name in self._embeddings:
                skill_emb = self._embeddings[name]
            else:
                text = f"{skill.manifest.name}\n{skill.manifest.description}"
                skill_emb = embedding_fn(text)

            similarity = _cosine_similarity(query_embedding, skill_emb)
            if similarity > 0:
                matches.append({
                    "name": name,
                    "skill": skill,
                    "score": similarity,
                })

        matches.sort(key=lambda m: m["score"], reverse=True)
        return matches[:top_k]

    def find_semantic(
        self, query: str, k: int = 1
    ) -> list[tuple["CapabilitySkill", float]]:
        """Semantic discovery using the configured embedder (Phase 3.19.3).

        Embeds *query*, runs cosine-similarity search against the vector
        store containing pre‑computed skill embeddings, and returns the
        top‑*k* matches with similarity scores.

        Uses the embedder's per‑session query cache to avoid recomputing
        embeddings during retries or re‑planning.

        Args:
            query: Natural-language description of the desired capability.
            k: Maximum number of results (default 1).

        Returns:
            List of ``(CapabilitySkill, similarity_score)`` tuples sorted
            descending by cosine similarity.  Returns an empty list when
            no skills match (or the similarity is ≤ 0).

        Raises:
            ValueError: If no embedder is configured on the registry.

        Note:
            This is used ONLY for discovery fallback — when the LLM fails
            to name a capability.  LLM‑chosen skills always take precedence.
        """
        if self._embedder is None:
            raise ValueError("find_semantic requires an embedder to be configured")

        query_embedding = self._embedder.embed_query(query)

        # Fast path: vector store (3.19.1)
        if self._vector_store is not None and len(self._vector_store) > 0:
            raw_results = self._vector_store.search(query_embedding, k=k)
            matches: list[tuple[CapabilitySkill, float]] = []
            for meta, score in raw_results:
                name = meta["name"]
                if name in self._skills:
                    matches.append((self._skills[name], score))
            return matches

        # Slow path: linear scan using pre‑computed embeddings
        results: list[tuple[CapabilitySkill, float]] = []
        for name, skill in self._skills.items():
            if name in self._embeddings:
                skill_emb = self._embeddings[name]
            else:
                text = _build_skill_text(skill)
                skill_emb = self._embedder.embed(text)

            similarity = _cosine_similarity(query_embedding, skill_emb)
            if similarity > 0:
                results.append((skill, similarity))

        results.sort(key=lambda item: item[1], reverse=True)
        return results[:k]

    def set_embedding(self, name: str, embedding: list[float]) -> None:
        """Store a pre-computed embedding for the skill named *name*.

        **PHASE 3.19.2**: Also updates ``skill.embedding`` on the
        registered ``CapabilitySkill`` object and inserts into the
        vector store (if attached).

        The skill must already be registered.
        """
        if name not in self._skills:
            raise ValueError(f"No skill registered with name {name!r}")
        self._embeddings[name] = embedding
        self._skills[name].embedding = embedding
        self._add_to_vector_store(name, embedding)

    # ── Hot‑reload (3.19.2) ──────────────────────────────────────────

    def reembed(self, name: str) -> None:
        """Re‑compute the embedding for the skill named *name*.

        Rebuilds the deterministic text representation, calls the
        embedder, updates the skill object, the embeddings table,
        and the vector store entry.

        This is the primary hot‑reload hook — call it when a skill's
        manifest or definition changes without restarting the process.

        Raises:
            ValueError: If no embedder is configured or the skill is
                        not registered.
        """
        if self._embedder is None:
            raise ValueError("Cannot reembed: no embedder configured")
        if name not in self._skills:
            raise ValueError(f"No skill registered with name {name!r}")

        skill = self._skills[name]
        text = _build_skill_text(skill)
        new_emb = self._embedder.embed(text)
        self._embeddings[name] = new_emb
        skill.embedding = new_emb
        self._update_vector_store(name, new_emb)  # 3.19.3: update, don't duplicate

    def reembed_all(self) -> None:
        """Re‑compute embeddings for every registered skill.

        This is a full cold‑restart of the embedding layer — useful
        when the embedding provider itself changes.
        """
        if self._embedder is None:
            raise ValueError("Cannot reembed all: no embedder configured")
        for name in list(self._skills.keys()):
            self.reembed(name)

    def ensure_embeddings(self) -> None:
        """Ensure every registered skill has an embedding.

        Any skill missing an embedding is re‑embedded.  Silently
        no‑ops when no embedder is set.
        """
        if self._embedder is None:
            return
        for name, skill in self._skills.items():
            if name not in self._embeddings or not self._embeddings[name]:
                self.reembed(name)


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Return the cosine similarity between two vectors.

    Returns 0.0 if either vector has zero magnitude.
    """
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    return dot / (norm1 * norm2) if norm1 and norm2 else 0.0
