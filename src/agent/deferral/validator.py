"""
Acyclicity validator for the agent deferral graph.

Walks the full directed graph (agent A → agent B if B is in A's
``defer_to`` list) with DFS to detect cycles.  Called once at
registration time — no runtime overhead.

Algorithm
---------
1. Build adjacency list from all registered agents.
2. Run DFS with a recursion stack (grey-set) on each unvisited node.
3. On back-edge: raise ``DeferralCycleError`` listing the cycle path
   (e.g. ``"support-agent → billing-agent → support-agent"``).

Self-deferral (an agent listing itself in ``defer_to``) is also
rejected as a trivial cycle.
"""

from __future__ import annotations

from typing import Dict, List, Set

from src.agent.registry import AgentRegistry


class DeferralGraphError(Exception):
    """Base error for deferral graph validation."""


class DeferralCycleError(DeferralGraphError):
    """Raised when the deferral graph contains a cycle."""


def validate_deferral_graph(registry: AgentRegistry) -> None:
    """Validate that the deferral graph has no cycles.

    Must be called *after* all agents are registered.  Walks every
    agent's ``defer_to`` list and runs DFS cycle detection.

    Parameters
    ----------
    registry:
        An ``AgentRegistry`` with all agents already registered.

    Raises
    ------
    DeferralCycleError:
        If any cycle (including self-deferral) is detected.  The
        error message lists the full cycle path.
    """
    agents = registry.list_agents()

    # Build adjacency list: agent_id → set of defer_to targets
    graph: Dict[str, List[str]] = {}
    for agent in agents:
        aid = agent.identity.agent_id
        graph[aid] = list(agent.defer_to or [])

    # DFS with grey-set (nodes currently in recursion stack)
    WHITE = 0   # unvisited
    GREY = 1    # in current DFS path
    BLACK = 2   # fully explored

    color: Dict[str, int] = {aid: WHITE for aid in graph}
    parent: Dict[str, str | None] = {}

    def _dfs(node: str) -> None:
        color[node] = GREY
        for neighbour in graph.get(node, []):
            if neighbour not in graph:
                # Reference to unknown agent — deferral graph error
                raise DeferralGraphError(
                    f"Agent {node!r} defers to {neighbour!r}, "
                    f"but {neighbour!r} is not registered"
                )
            if color[neighbour] == GREY:
                # Back-edge found — extract cycle path
                path = _extract_cycle(parent, node, neighbour)
                raise DeferralCycleError(
                    f"Deferral cycle detected: "
                    + " → ".join(path)
                )
            if color[neighbour] == WHITE:
                parent[neighbour] = node
                _dfs(neighbour)
        color[node] = BLACK

    # Self-deferral check (trivial cycle)
    for aid, targets in graph.items():
        if aid in targets:
            raise DeferralCycleError(
                f"Deferral cycle detected: {aid} → {aid} (self-deferral)"
            )

    for node in graph:
        if color[node] == WHITE:
            _dfs(node)


def _extract_cycle(
    parent: Dict[str, str | None],
    from_node: str,
    to_node: str,
) -> List[str]:
    """Extract the cycle path from back-edge *from_node → to_node*.

    Walks backwards from *from_node* through *parent* pointers until
    reaching *to_node*, building the path from *to_node* forward.
    """
    path: List[str] = [to_node]
    current = from_node
    while current is not None and current != to_node:
        path.append(current)
        current = parent.get(current)
    path.append(to_node)
    path.reverse()
    return path
