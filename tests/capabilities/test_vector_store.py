"""
Unit tests for VectorStore (PHASE 3.19.1).

Tests the in-memory vector store used for semantic skill-discovery fallback.
Uses numpy-based cosine similarity — no external index dependency.
"""

from __future__ import annotations

import pytest

from src.capabilities.discovery.vector_store import VectorStore


class TestVectorStore:
    """Tests for the VectorStore class."""

    def test_add_and_search_single(self) -> None:
        """Single vector added can be found by searching."""
        store = VectorStore()
        store.add([1.0, 0.0], {"name": "skill.a"})

        results = store.search([1.0, 0.0], k=1)
        assert len(results) == 1
        meta, score = results[0]
        assert meta["name"] == "skill.a"
        assert score == pytest.approx(1.0)

    def test_search_returns_top_k(self) -> None:
        """Search returns exactly k results in descending relevance."""
        store = VectorStore()
        store.add([1.0, 0.0, 0.0], {"name": "skill.a"})
        store.add([0.0, 1.0, 0.0], {"name": "skill.b"})
        store.add([0.0, 0.0, 1.0], {"name": "skill.c"})

        # Query closer to skill.a
        results = store.search([0.9, 0.1, 0.0], k=2)
        assert len(results) == 2
        assert results[0][0]["name"] == "skill.a"
        assert results[0][1] > results[1][1]

    def test_search_empty_store(self) -> None:
        """Empty store returns empty list."""
        store = VectorStore()
        results = store.search([1.0, 0.0], k=5)
        assert results == []

    def test_search_exact_match(self) -> None:
        """Identical vectors produce similarity == 1.0."""
        store = VectorStore()
        store.add([0.5, 0.5, 0.5, 0.5], {"name": "exact"})

        results = store.search([0.5, 0.5, 0.5, 0.5], k=1)
        assert len(results) == 1
        _, score = results[0]
        assert score == pytest.approx(1.0, abs=1e-6)

    def test_search_orthogonal(self) -> None:
        """Orthogonal vectors produce similarity == 0.0."""
        store = VectorStore()
        store.add([1.0, 0.0], {"name": "ortho"})

        results = store.search([0.0, 1.0], k=1)
        assert len(results) == 1
        _, score = results[0]
        assert score == pytest.approx(0.0, abs=1e-6)

    def test_search_opposite(self) -> None:
        """Opposite vectors produce similarity == -1.0."""
        store = VectorStore()
        store.add([1.0, 0.0], {"name": "opposite"})

        results = store.search([-1.0, 0.0], k=1)
        assert len(results) == 1
        _, score = results[0]
        assert score == pytest.approx(-1.0, abs=1e-6)

    def test_k_larger_than_store(self) -> None:
        """When k > store size, return all items."""
        store = VectorStore()
        store.add([1.0, 0.0], {"name": "a"})
        store.add([0.0, 1.0], {"name": "b"})

        results = store.search([0.5, 0.5], k=10)
        assert len(results) == 2

    def test_normalises_on_insert(self) -> None:
        """Vectors are normalized on insert — similarity is cosine."""
        store = VectorStore()
        # Insert non-unit vector
        store.add([3.0, 4.0], {"name": "norm"})  # length 5

        # Query with unit vector in same direction
        results = store.search([0.6, 0.8], k=1)
        assert len(results) == 1
        _, score = results[0]
        assert score == pytest.approx(1.0, abs=1e-6)

    def test_clear_empties_store(self) -> None:
        """Clear removes all vectors."""
        store = VectorStore()
        store.add([1.0, 0.0], {"name": "x"})
        store.clear()
        assert len(store) == 0
        assert store.search([1.0, 0.0], k=1) == []

    def test_len_reflects_count(self) -> None:
        """__len__ returns the number of stored vectors."""
        store = VectorStore()
        assert len(store) == 0
        store.add([1.0, 0.0], {"name": "a"})
        assert len(store) == 1
        store.add([0.0, 1.0], {"name": "b"})
        assert len(store) == 2

    def test_zero_vector_handled(self) -> None:
        """Zero-vector insert doesn't raise and gets zero similarity."""
        store = VectorStore()
        store.add([0.0, 0.0, 0.0], {"name": "zero"})

        results = store.search([1.0, 0.0, 0.0], k=1)
        assert len(results) == 1
        _, score = results[0]
        assert score == pytest.approx(0.0, abs=1e-6)


class TestVectorStoreUpdate:
    """Tests for VectorStore.update() (Phase 3.19.3)."""

    def test_update_replaces_vector(self) -> None:
        """Update changes the stored vector for an existing name."""
        store = VectorStore()
        store.add([1.0, 0.0], {"name": "skill.a"})

        # Before update: query [0.0, 1.0] is orthogonal → ~0
        results_before = store.search([0.0, 1.0], k=1)
        assert results_before[0][1] == pytest.approx(0.0, abs=1e-6)

        # Update to a vector aligned with [0.0, 1.0]
        store.update("skill.a", [0.0, 1.0])

        results_after = store.search([0.0, 1.0], k=1)
        assert results_after[0][0]["name"] == "skill.a"
        assert results_after[0][1] == pytest.approx(1.0, abs=1e-6)

    def test_update_raises_for_missing_name(self) -> None:
        """Update raises ValueError when no entry with that name exists."""
        store = VectorStore()
        store.add([1.0, 0.0], {"name": "skill.a"})

        with pytest.raises(ValueError, match="skill.b"):
            store.update("skill.b", [0.0, 1.0])

    def test_update_maintains_store_length(self) -> None:
        """Update does not change the number of entries."""
        store = VectorStore()
        store.add([1.0, 0.0], {"name": "a"})
        store.add([0.0, 1.0], {"name": "b"})
        assert len(store) == 2

        store.update("a", [0.5, 0.5])
        assert len(store) == 2

    def test_update_normalises_vector(self) -> None:
        """Update normalises the new embedding before storing."""
        store = VectorStore()
        store.add([1.0, 0.0], {"name": "norm"})

        # Insert non-unit vector — should be normalized to [0.6, 0.8]
        store.update("norm", [3.0, 4.0])

        results = store.search([0.6, 0.8], k=1)
        assert results[0][1] == pytest.approx(1.0, abs=1e-6)

    def test_update_empty_store_raises(self) -> None:
        """Update on empty store raises ValueError."""
        store = VectorStore()
        with pytest.raises(ValueError, match="missing"):
            store.update("missing", [1.0, 0.0])
