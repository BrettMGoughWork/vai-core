"""
DAG Validator — Agent Decomposition
=====================================

Validates that a list of ``SubtaskSpec`` values forms a valid directed
acyclic graph.  Called by the orchestrator before fan-out.

Rules enforced (Section 4.2 of ROADMAP-agent-decomposition.md):
  1. All ``id`` values unique within the plan.
  2. All ``depends_on`` entries reference valid ids.
  3. No self-dependency.
  4. Graph is acyclic (DFS cycle detection).
"""

from __future__ import annotations

from src.agent.types.decomposition import SubtaskSpec


class DagValidationError(ValueError):
    """Raised when a decomposition DAG fails validation."""


def validate_dag(subtasks: list[SubtaskSpec]) -> None:
    """Validate DAG invariants. Raises ``DagValidationError`` on violation."""
    ids = {s.id for s in subtasks}

    # 1. Uniqueness
    if len(ids) != len(subtasks):
        raise DagValidationError("Duplicate subtask IDs")

    # 2. Missing deps and self-deps
    for s in subtasks:
        for dep in s.depends_on:
            if dep not in ids:
                raise DagValidationError(
                    f"Subtask {s.id!r} depends on unknown subtask {dep!r}"
                )
            if dep == s.id:
                raise DagValidationError(
                    f"Subtask {s.id!r} depends on itself"
                )

    # 3. Cycle detection via DFS
    _check_cycles(subtasks)


def topological_sort(subtasks: list[SubtaskSpec]) -> list[SubtaskSpec]:
    """Return subtasks in topological (dependency) order.

    Raises ``DagValidationError`` if the graph contains a cycle.
    """
    validate_dag(subtasks)

    id_map = {s.id: s for s in subtasks}
    visited: set[str] = set()
    result: list[SubtaskSpec] = []

    def _visit(node_id: str) -> None:
        if node_id in visited:
            return
        visited.add(node_id)
        node = id_map[node_id]
        for dep_id in node.depends_on:
            _visit(dep_id)
        result.append(node)

    for s in subtasks:
        _visit(s.id)

    return result


# ── Internal ──────────────────────────────────────────────────────────────


def _build_adjacency(subtasks: list[SubtaskSpec]) -> dict[str, list[str]]:
    """Build adjacency list: subtask_id → list of subtask_ids it depends on."""
    adjacency: dict[str, list[str]] = {}
    for s in subtasks:
        adjacency[s.id] = list(s.depends_on)
    return adjacency


def _check_cycles(subtasks: list[SubtaskSpec]) -> None:
    """DFS-based cycle detection. Raises ``DagValidationError`` if cycle found."""
    adjacency = _build_adjacency(subtasks)

    UNVISITED = 0
    VISITING = 1
    VISITED = 2

    state: dict[str, int] = {s.id: UNVISITED for s in subtasks}

    def _dfs(node_id: str) -> None:
        state[node_id] = VISITING
        for dep_id in adjacency.get(node_id, []):
            if state[dep_id] == VISITING:
                raise DagValidationError(
                    f"Cycle detected: {node_id!r} → {dep_id!r}"
                )
            if state[dep_id] == UNVISITED:
                _dfs(dep_id)
        state[node_id] = VISITED

    for s in subtasks:
        if state[s.id] == UNVISITED:
            _dfs(s.id)
