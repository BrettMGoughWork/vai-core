from __future__ import annotations

import copy
from typing import Dict, List, Optional

from src.core.types.subgoal import Subgoal, SubgoalLifecycleState
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord, SubgoalMemorySnapshot


class SubgoalMemory:
    """
    Pure, deterministic in-memory store for Subgoal objects.

    Subgoals are stored as SubgoalMemoryRecord (not as Subgoal instances).
    All returned Subgoals are reconstructed from records.
    No I/O, no side effects, no external state.
    """

    def __init__(self) -> None:
        self._store: Dict[str, SubgoalMemoryRecord] = {}

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def put(self, subgoal: Subgoal) -> None:
        """Convert subgoal to a record and store it. Overwrites any existing entry."""
        self._store[subgoal.subgoal_id] = SubgoalMemoryRecord(
            subgoal_id=subgoal.subgoal_id,
            parent_id=subgoal.parent_id,
            state=subgoal.state.value,
            goal=subgoal.goal,
            context=copy.deepcopy(dict(subgoal.context)),
            metadata=copy.deepcopy(dict(subgoal.metadata)),
            created_at=subgoal.created_at,
        )

    def get(self, subgoal_id: str) -> Optional[Subgoal]:
        """Reconstruct and return a Subgoal from the stored record, or None."""
        record = self._store.get(subgoal_id)
        if record is None:
            return None
        return self._record_to_subgoal(record)

    def get_record(self, subgoal_id: str) -> Optional[SubgoalMemoryRecord]:
        """Return the raw SubgoalMemoryRecord for subgoal_id, or None."""
        return self._store.get(subgoal_id)

    def exists(self, subgoal_id: str) -> bool:
        return subgoal_id in self._store

    def list_all(self) -> List[Subgoal]:
        """Return all stored subgoals, sorted by created_at then subgoal_id."""
        records = sorted(
            self._store.values(),
            key=lambda r: (r.created_at, r.subgoal_id),
        )
        return [self._record_to_subgoal(r) for r in records]

    # ------------------------------------------------------------------
    # Retrieval helpers (return records, not Subgoals)
    # ------------------------------------------------------------------

    def get_chain(self, subgoal_id: str) -> List[SubgoalMemoryRecord]:
        """
        Return the chain of records from root → leaf ending at subgoal_id.

        Walks parent_id links upward with cycle protection.
        Returns an empty list if subgoal_id is not found.
        """
        chain: List[SubgoalMemoryRecord] = []
        current_id: Optional[str] = subgoal_id
        visited: set = set()

        while current_id and current_id not in visited:
            visited.add(current_id)
            record = self._store.get(current_id)
            if record is None:
                break
            chain.append(record)
            current_id = record.parent_id

        chain.reverse()
        return chain

    def get_children(self, parent_id: str) -> List[SubgoalMemoryRecord]:
        """Return all records whose parent_id matches, sorted by created_at then subgoal_id."""
        return sorted(
            [r for r in self._store.values() if r.parent_id == parent_id],
            key=lambda r: (r.created_at, r.subgoal_id),
        )

    # ------------------------------------------------------------------
    # Snapshotting
    # ------------------------------------------------------------------

    def snapshot(self) -> SubgoalMemorySnapshot:
        """Return an immutable snapshot of the current store, sorted deterministically."""
        records = tuple(
            sorted(self._store.values(), key=lambda r: (r.created_at, r.subgoal_id))
        )
        return SubgoalMemorySnapshot(records=records)

    def load_snapshot(self, snapshot: SubgoalMemorySnapshot) -> None:
        """Replace the current store with the contents of a snapshot."""
        self._store = {r.subgoal_id: r for r in snapshot.records}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _record_to_subgoal(self, record: SubgoalMemoryRecord) -> Subgoal:
        return Subgoal(
            subgoal_id=record.subgoal_id,
            goal=record.goal,
            context=copy.deepcopy(record.context),
            metadata=copy.deepcopy(record.metadata),
            parent_id=record.parent_id,
            state=SubgoalLifecycleState(record.state),
            created_at=record.created_at,
        )
