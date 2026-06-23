from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from src.agent.types.plan import Plan
from src.agent.memory.plan_memory_types import PlanMemoryRecord, PlanMemorySnapshot


class PlanMemory:
    """
    Pure, deterministic in-memory store for Plan objects.

    Plans are stored as PlanMemoryRecord (not as Plan instances).
    All returned Plans are reconstructed from records.
    No I/O, no side effects, no external state.

    Because Plan carries no plan_id, subgoal_id, segments, created_at, or metadata,
    those fields must be supplied by the caller at put() time.
    """

    def __init__(self) -> None:
        self._store: Dict[str, PlanMemoryRecord] = {}

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def put(
        self,
        plan: Plan,
        plan_id: str,
        subgoal_id: str,
        segments: List[str],
        created_at: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Convert plan to a record and store it. Overwrites any existing entry.

        plan_id, subgoal_id, segments, and created_at must be supplied by the
        caller — Plan itself carries none of these fields.
        """
        self._store[plan_id] = PlanMemoryRecord(
            plan_id=plan_id,
            subgoal_id=subgoal_id,
            segments=list(segments),
            created_at=created_at,
            metadata=copy.deepcopy(metadata or {}),
            intent=plan.intent,
            targetskillid=plan.targetskillid,
            arguments=copy.deepcopy(plan.arguments),
            reasoning_summary=plan.reasoning_summary,
        )

    def get(self, plan_id: str) -> Optional[Plan]:
        """
        Reconstruct and return a Plan from the stored record, or None.

        Note: the returned Plan carries no plan_id/subgoal_id — use get_record()
        when identity fields are needed.
        """
        record = self._store.get(plan_id)
        if record is None:
            return None
        return self._record_to_plan(record)

    def get_record(self, plan_id: str) -> Optional[PlanMemoryRecord]:
        """Return the raw record for plan_id, or None. Preserves all identity fields."""
        return self._store.get(plan_id)

    def exists(self, plan_id: str) -> bool:
        return plan_id in self._store

    def list_all(self) -> List[Plan]:
        """Return all stored plans as Plan objects, sorted by created_at then plan_id."""
        records = sorted(
            self._store.values(),
            key=lambda r: (r.created_at, r.plan_id),
        )
        return [self._record_to_plan(r) for r in records]

    # ------------------------------------------------------------------
    # Retrieval helpers (return records)
    # ------------------------------------------------------------------

    def get_by_subgoal(self, subgoal_id: str) -> List[PlanMemoryRecord]:
        """Return all records associated with a given subgoal, sorted by created_at then plan_id."""
        return sorted(
            [r for r in self._store.values() if r.subgoal_id == subgoal_id],
            key=lambda r: (r.created_at, r.plan_id),
        )

    def get_segments(self, plan_id: str) -> List[str]:
        """Return the segment IDs associated with a plan, or an empty list if not found."""
        record = self._store.get(plan_id)
        return list(record.segments) if record else []

    def get_latest_for_subgoal(self, subgoal_id: str) -> Optional[PlanMemoryRecord]:
        """
        Return the most recent plan record for a subgoal, or None.

        'Most recent' is determined by (created_at, plan_id) sort order —
        deterministic as long as created_at is a canonical ISO string.
        """
        candidates = self.get_by_subgoal(subgoal_id)
        return candidates[-1] if candidates else None

    # ------------------------------------------------------------------
    # Bulk removal (used by eviction orchestrator)
    # ------------------------------------------------------------------

    def remove(self, record_ids: List[str]) -> None:
        """Remove records by ID. Missing IDs are silently skipped."""
        for rid in record_ids:
            self._store.pop(rid, None)

    # ------------------------------------------------------------------
    # Snapshotting
    # ------------------------------------------------------------------

    def snapshot(self) -> PlanMemorySnapshot:
        """Return an immutable snapshot of the current store, sorted deterministically."""
        records = tuple(
            sorted(self._store.values(), key=lambda r: (r.created_at, r.plan_id))
        )
        return PlanMemorySnapshot(records=records)

    def load_snapshot(self, snapshot: PlanMemorySnapshot) -> None:
        """Replace the current store with the contents of a snapshot."""
        self._store = {r.plan_id: r for r in snapshot.records}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _record_to_plan(self, record: PlanMemoryRecord) -> Plan:
        return Plan(
            intent=record.intent,
            targetskillid=record.targetskillid,
            arguments=copy.deepcopy(record.arguments),
            reasoning_summary=record.reasoning_summary,
        )
