"""
S5.6 — AgentStateStore Interface
=================================

Defines the persistence boundary for agent runtime state (S5).

AgentStateStore is a pure storage interface — it persists and retrieves
complete ``AgentState`` snapshots as opaque blobs.  It does **not**
interpret, validate, or mutate agent semantics.

All backends implement this interface:
- In-memory (tests / ephemeral agents)
- File-backed (JSON files, atomic writes via temp+rename)
- SQLite (transactional snapshots, single-file)
- Strategy-backed (future — Strategy stores opaque blobs under namespaced keys)

Contract
--------
- ``save()`` must write a full snapshot (copy-on-write, no in-place mutation)
- ``load()`` must return the last complete snapshot or ``None``
- ``list_agent_ids()`` must return all known agent IDs
- All methods are synchronous and deterministic
- Storage is opaque — the store never inspects ``AgentState`` contents
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from src.agent.interfaces.agent_state import AgentState


class AgentStateStore(ABC):
    """Persistent storage for ``AgentState`` snapshots.

    Implementations must provide:
    - Atomic writes (no partial snapshots)
    - Full-snapshot semantics (no delta / incremental)
    - No mutation of the passed-in state
    """

    @abstractmethod
    def save(self, agent_id: str, state: AgentState) -> None:
        """Persist a complete snapshot of the agent's state.

        Args:
            agent_id: Unique agent identifier.
            state: The ``AgentState`` to persist.  Must not be mutated.

        Raises:
            StoreError: If the write fails.
        """

    @abstractmethod
    def load(self, agent_id: str) -> Optional[AgentState]:
        """Load the most recent snapshot for an agent.

        Args:
            agent_id: Unique agent identifier.

        Returns:
            The persisted ``AgentState``, or ``None`` if no state exists.
        """

    @abstractmethod
    def list_agent_ids(self) -> List[str]:
        """Return all agent IDs that have persisted state.

        Used by the supervisor to discover agents after a restart.
        """


class StoreError(Exception):
    """Base error for AgentStateStore operations."""
