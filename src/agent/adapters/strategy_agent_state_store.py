"""
Strategy-backed AgentStateStore — future adapter.

Strategy stores opaque blobs under namespaced keys (``agentstate/<agent_id>``).
Strategy does **not** parse or interpret agent state — it is a pure
KV/metadata backend.

This adapter is a **placeholder** for when the Strategy stratum exposes
a suitable KV interface.  Currently raises ``NotImplementedError``.
"""

from __future__ import annotations

from typing import List, Optional

from src.agent.interfaces.agent_state import AgentState
from src.agent.interfaces.agent_state_store import AgentStateStore


class StrategyAgentStateStore(AgentStateStore):
    """Future Strategy-backed agent state store.

    When Strategy exposes a generic KV/metadata interface, this adapter
    will serialise ``AgentState`` to JSON blobs and store them under
    the key ``agentstate/<agent_id>``.

    Strategy remains ignorant of agent semantics.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "StrategyAgentStateStore is not yet implemented. "
            "Use MemoryAgentStateStore, FileAgentStateStore, or "
            "SQLiteAgentStateStore instead."
        )

    def save(self, agent_id: str, state: AgentState) -> None:
        raise NotImplementedError

    def load(self, agent_id: str) -> Optional[AgentState]:
        raise NotImplementedError

    def list_agent_ids(self) -> List[str]:
        raise NotImplementedError
