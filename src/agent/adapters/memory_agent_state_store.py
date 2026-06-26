"""
In-memory AgentStateStore — ephemeral, for tests and transient agents.

Not durable across process restarts.  Uses a plain ``dict`` keyed by
``agent_id``.  Fully thread-safe via ``threading.Lock`` — concurrent
access from decomposition worker threads is safe.
"""

from __future__ import annotations

import copy
import threading
from typing import Dict, List, Optional

from src.agent.interfaces.agent_state import AgentState
from src.agent.interfaces.agent_state_store import AgentStateStore, StoreError


class MemoryAgentStateStore(AgentStateStore):
    """In-memory agent state store.

    Stores full snapshots in a dict.  Provides ``save()``, ``load()``,
    and ``list_agent_ids()``.  Not durable across restarts.

    Thread-safe: all public methods are protected by a ``threading.Lock``
    so concurrent access from decomposition worker threads is safe.
    """

    def __init__(self) -> None:
        self._store: Dict[str, AgentState] = {}
        self._lock = threading.Lock()

    def save(self, agent_id: str, state: AgentState) -> None:
        if not agent_id:
            raise StoreError("agent_id must be non-empty")
        # Store a deep copy to guarantee immutability
        with self._lock:
            self._store[agent_id] = copy.deepcopy(state)

    def load(self, agent_id: str) -> Optional[AgentState]:
        with self._lock:
            state = self._store.get(agent_id)
        # Deep copy outside the lock — independent work once we have the reference.
        return copy.deepcopy(state) if state is not None else None

    def list_agent_ids(self) -> List[str]:
        with self._lock:
            return list(self._store.keys())
