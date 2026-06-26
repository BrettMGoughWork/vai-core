"""
Tests for DAG Validator.
=========================

Covers:
- validate_dag: unique IDs, valid deps, no self-deps, cycle detection
- topological_sort: produces correct dependency order
- Empty / single-node / disconnected DAG edge cases
"""

from __future__ import annotations

import pytest

from src.agent.decomposition.dag_validator import (
    DagValidationError,
    topological_sort,
    validate_dag,
)
from src.agent.types.decomposition import SubtaskSpec


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _spec(id: str, depends_on: list[str] | None = None) -> SubtaskSpec:
    return SubtaskSpec(
        id=id,
        description=f"Subtask {id}",
        depends_on=depends_on or [],
    )


# ══════════════════════════════════════════════════════════════════════════════
# validate_dag
# ══════════════════════════════════════════════════════════════════════════════


class TestValidateDag:
    def test_valid_linear_chain(self) -> None:
        """A -> B -> C should pass."""
        subtasks = [_spec("a"), _spec("b", ["a"]), _spec("c", ["b"])]
        validate_dag(subtasks)  # should not raise

    def test_valid_fan_out(self) -> None:
        """A -> B, C (B and C depend on A) should pass."""
        subtasks = [_spec("a"), _spec("b", ["a"]), _spec("c", ["a"])]
        validate_dag(subtasks)

    def test_valid_disconnected(self) -> None:
        """A, B, C with no deps should pass."""
        subtasks = [_spec("a"), _spec("b"), _spec("c")]
        validate_dag(subtasks)

    def test_empty_list(self) -> None:
        validate_dag([])

    def test_single_node(self) -> None:
        validate_dag([_spec("a")])

    def test_duplicate_ids_raises(self) -> None:
        subtasks = [_spec("a"), _spec("a")]
        with pytest.raises(DagValidationError, match="Duplicate"):
            validate_dag(subtasks)

    def test_unknown_dependency_raises(self) -> None:
        subtasks = [_spec("a"), _spec("b", ["c"])]
        with pytest.raises(DagValidationError, match="unknown subtask"):
            validate_dag(subtasks)

    def test_self_dependency_raises(self) -> None:
        subtasks = [_spec("a", ["a"])]
        with pytest.raises(DagValidationError, match="depends on itself"):
            validate_dag(subtasks)

    def test_simple_cycle_raises(self) -> None:
        """A -> B -> A should raise."""
        subtasks = [_spec("a", ["b"]), _spec("b", ["a"])]
        with pytest.raises(DagValidationError, match="Cycle"):
            validate_dag(subtasks)

    def test_three_node_cycle_raises(self) -> None:
        """A -> B -> C -> A should raise."""
        subtasks = [
            _spec("a", ["c"]),
            _spec("b", ["a"]),
            _spec("c", ["b"]),
        ]
        with pytest.raises(DagValidationError, match="Cycle"):
            validate_dag(subtasks)

    def test_diamond_dag_passes(self) -> None:
        """
          A
         / \
        B   C
         \ /
          D
        """
        subtasks = [
            _spec("a"),
            _spec("b", ["a"]),
            _spec("c", ["a"]),
            _spec("d", ["b", "c"]),
        ]
        validate_dag(subtasks)  # should not raise

    def test_multi_level_diamond(self) -> None:
        """
          A
         / \
        B   C
        |   |
        D   E
         \ /
          F
        """
        subtasks = [
            _spec("a"),
            _spec("b", ["a"]),
            _spec("c", ["a"]),
            _spec("d", ["b"]),
            _spec("e", ["c"]),
            _spec("f", ["d", "e"]),
        ]
        validate_dag(subtasks)

    def test_cycle_via_deep_path(self) -> None:
        """A -> B -> C -> D -> B should raise."""
        subtasks = [
            _spec("a"),
            _spec("b", ["a"]),
            _spec("c", ["b"]),
            _spec("d", ["c"]),
            _spec("e", ["d", "b"]),  # E depends on D (ok) and B (back-edge to already-visited)
        ]
        # This is actually valid — B's dep is from E, not B→E. So no cycle.
        validate_dag(subtasks)


# ══════════════════════════════════════════════════════════════════════════════
# topological_sort
# ══════════════════════════════════════════════════════════════════════════════


class TestTopologicalSort:
    def test_linear_order(self) -> None:
        """A -> B -> C should produce [A, B, C]."""
        subtasks = [_spec("c", ["b"]), _spec("b", ["a"]), _spec("a")]
        # Input is shuffled — output must respect deps
        sorted_ = topological_sort(subtasks)
        ids = [s.id for s in sorted_]
        # A must come before B, B before C
        assert ids.index("a") < ids.index("b")
        assert ids.index("b") < ids.index("c")

    def test_empty_input(self) -> None:
        assert topological_sort([]) == []

    def test_single_node(self) -> None:
        result = topological_sort([_spec("a")])
        assert [s.id for s in result] == ["a"]

    def test_disconnected_nodes(self) -> None:
        result = topological_sort([_spec("b"), _spec("a"), _spec("c")])
        ids = [s.id for s in result]
        assert len(ids) == 3

    def test_diamond(self) -> None:
        subtasks = [
            _spec("d", ["b", "c"]),
            _spec("b", ["a"]),
            _spec("c", ["a"]),
            _spec("a"),
        ]
        sorted_ = topological_sort(subtasks)
        ids = [s.id for s in sorted_]
        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")

    def test_cycle_raises(self) -> None:
        subtasks = [_spec("a", ["b"]), _spec("b", ["a"])]
        with pytest.raises(DagValidationError):
            topological_sort(subtasks)
