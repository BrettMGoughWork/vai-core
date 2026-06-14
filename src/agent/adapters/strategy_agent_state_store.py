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
    """Deprecated — left as a placeholder for S4-backed agent state.

    .. deprecated::
        This stub was never implemented. It is no longer exported from
        ``src.agent``.  Use ``MemoryAgentStateStore``, ``FileAgentStateStore``,
        or ``SQLiteAgentStateStore`` instead.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "StrategyAgentStateStore is deprecated and no longer exported. "
            "Use MemoryAgentStateStore, FileAgentStateStore, or "
            "SQLiteAgentStateStore instead."
        )

    def save(self, agent_id: str, state: AgentState) -> None:
        raise NotImplementedError

    def load(self, agent_id: str) -> Optional[AgentState]:
        raise NotImplementedError

    def list_agent_ids(self) -> List[str]:
        raise NotImplementedError
