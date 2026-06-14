"""
In-memory AgentStateStore — ephemeral, for tests and transient agents.

Not durable across process restarts.  Uses a plain ``dict`` keyed by
``agent_id``.  Thread-safe for reads but last-write-wins for concurrent
writes (acceptable for single-supervisor scenarios).
"""

from __future__ import annotations

import copy
from typing import Dict, List, Optional

from src.agent.interfaces.agent_state import AgentState
from src.agent.interfaces.agent_state_store import AgentStateStore, StoreError


class MemoryAgentStateStore(AgentStateStore):
    """In-memory agent state store.

    Stores full snapshots in a dict.  Provides ``save()``, ``load()``,
    and ``list_agent_ids()``.  Not durable across restarts.
    """

    def __init__(self) -> None:
        self._store: Dict[str, AgentState] = {}

    def save(self, agent_id: str, state: AgentState) -> None:
        if not agent_id:
            raise StoreError("agent_id must be non-empty")
        # Store a deep copy to guarantee immutability
        self._store[agent_id] = copy.deepcopy(state)

    def load(self, agent_id: str) -> Optional[AgentState]:
        state = self._store.get(agent_id)
        # Return a deep copy to guarantee immutability on read
        return copy.deepcopy(state) if state is not None else None

    def list_agent_ids(self) -> List[str]:
        return list(self._store.keys())
