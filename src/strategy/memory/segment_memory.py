from __future__ import annotations

import copy
from dataclasses import asdict
from typing import Dict, List, Optional

from src.strategy.types.plan_segment import PlanSegment
from src.strategy.memory.segment_memory_types import SegmentMemoryRecord, SegmentMemorySnapshot


class SegmentMemory:
    """
    Pure, deterministic in-memory store for PlanSegment objects.

    Segments are stored as SegmentMemoryRecord (not as PlanSegment instances).
    All returned PlanSegments are reconstructed from records.
    No I/O, no side effects, no external state.
    """

    def __init__(self) -> None:
        self._store: Dict[str, SegmentMemoryRecord] = {}

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def put(self, segment: PlanSegment, parent_id: Optional[str] = None) -> None:
        """
        Convert segment to a record and store it. Overwrites any existing entry.

        A normalised PlanSegment is created from copies of the input fields so
        that the stored segment_id is always consistent with the stored content.
        """
        steps = list(segment.steps)
        context = copy.deepcopy(dict(segment.context))
        metadata = copy.deepcopy(dict(segment.metadata))

        normalised = PlanSegment(
            subgoal_id=segment.subgoal_id,
            steps=steps,
            context=context,
            metadata=metadata,
            skills=list(segment.skills),
            created_at=segment.created_at,
        )

        segment_id = normalised.segment_id

        # --- Preserve behavioural-observation fields if overwriting an existing record ---
        prev_record = self._store.get(segment_id)

        previous_output = prev_record.previous_output if prev_record else None
        last_output = prev_record.last_output if prev_record else None
        behavioural_delta = prev_record.behavioural_delta if prev_record else None
        behavioural_signals = list(prev_record.behavioural_signals) if prev_record else []

        # --- Construct new record including behavioural fields ---
        self._store[segment_id] = SegmentMemoryRecord(
            segment_id=segment_id,
            parent_id=parent_id,
            subgoal_id=normalised.subgoal_id,
            state=None,
            content=list(normalised.steps),
            created_at=normalised.created_at,
            context=copy.deepcopy(dict(normalised.context)),
            metadata=copy.deepcopy(dict(normalised.metadata)),
            skills=list(normalised.skills),
        
            # --- 2.6.2 behavioural-observation fields ---
            previous_output=previous_output,
            last_output=last_output,
            behavioural_delta=behavioural_delta,

            # --- 2.6.3 behavioural drift signals ---
            behavioural_signals=behavioural_signals,

            # --- 3.8.8 error preservation ---
            error=prev_record.error if prev_record else None,
        )

    def get(self, segment_id: str) -> Optional[PlanSegment]:
        """Reconstruct and return a PlanSegment from the stored record, or None."""
        record = self._store.get(segment_id)
        if record is None:
            return None
        return self._record_to_segment(record)

    def get_record(self, segment_id: str) -> Optional[SegmentMemoryRecord]:
        """Return the raw SegmentMemoryRecord for segment_id, or None."""
        return self._store.get(segment_id)

    def put_record(self, record: SegmentMemoryRecord) -> None:
        """Directly store a SegmentMemoryRecord, overwriting any existing entry."""
        self._store[record.segment_id] = record

    def exists(self, segment_id: str) -> bool:
        return segment_id in self._store

    def list_all(self) -> List[PlanSegment]:
        """Return all stored segments, sorted by created_at then segment_id."""
        records = sorted(
            self._store.values(),
            key=lambda r: (r.created_at, r.segment_id),
        )
        return [self._record_to_segment(r) for r in records]

    # ------------------------------------------------------------------
    # Retrieval helpers (return records, not PlanSegments)
    # ------------------------------------------------------------------

    def get_chain(self, segment_id: str) -> List[SegmentMemoryRecord]:
        """
        Return the chain of records from root → leaf ending at segment_id.

        Walks parent_id links upward with cycle protection.
        Returns an empty list if segment_id is not found.
        Silently truncates on broken parent links.
        """
        chain: List[SegmentMemoryRecord] = []
        current_id: Optional[str] = segment_id
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

    def get_children(self, parent_id: str) -> List[SegmentMemoryRecord]:
        """Return all records whose parent_id matches, sorted by created_at then segment_id."""
        return sorted(
            [r for r in self._store.values() if r.parent_id == parent_id],
            key=lambda r: (r.created_at, r.segment_id),
        )

    def get_by_subgoal(self, subgoal_id: str) -> List[SegmentMemoryRecord]:
        """Return all records associated with a given subgoal, sorted by created_at then segment_id."""
        return sorted(
            [r for r in self._store.values() if r.subgoal_id == subgoal_id],
            key=lambda r: (r.created_at, r.segment_id),
        )

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

    def snapshot(self) -> SegmentMemorySnapshot:
        """Return an immutable snapshot of the current store, sorted deterministically."""
        
        sorted_records = sorted(
            self._store.values(),
            key=lambda r: (r.created_at, r.segment_id),
        )
        
        snapshot_records = tuple(
            SegmentMemoryRecord(**asdict(rec))
            for rec in sorted_records
        )
        return SegmentMemorySnapshot(records=snapshot_records)

    def load_snapshot(self, snapshot: SegmentMemorySnapshot) -> None:
        """Replace the current store with the contents of a snapshot."""
        self._store = {r.segment_id: r for r in snapshot.records}

    # ------------------------------------------------------------------
    # 2.6.3 Behavioural signal management
    # ------------------------------------------------------------------

    def update_behavioural_signals(
        self, segment_id: str, signals: List["BehaviouralSignal"]
    ) -> None:
        """
        Replace the behavioural_signals on a segment record.

        If the segment does not exist this is a no-op.
        The signals list is copied to prevent external mutation.
        """
        record = self._store.get(segment_id)
        if record is None:
            return

        self._store[segment_id] = SegmentMemoryRecord(
            segment_id=record.segment_id,
            parent_id=record.parent_id,
            subgoal_id=record.subgoal_id,
            state=record.state,
            content=list(record.content),
            created_at=record.created_at,
            context=copy.deepcopy(record.context),
            metadata=copy.deepcopy(record.metadata),
            skills=list(record.skills),
            previous_output=record.previous_output,
            last_output=record.last_output,
            behavioural_delta=record.behavioural_delta,
            behavioural_signals=list(signals),
            error=record.error,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _record_to_segment(self, record: SegmentMemoryRecord) -> PlanSegment:
        return PlanSegment(
            subgoal_id=record.subgoal_id,
            steps=list(record.content),
            context=copy.deepcopy(record.context),
            metadata=copy.deepcopy(record.metadata),
            skills=list(record.skills),
            created_at=record.created_at,
        )
