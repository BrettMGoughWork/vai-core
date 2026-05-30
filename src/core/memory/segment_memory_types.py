from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class SegmentMemoryRecord:
    """
    Pure, JSON-serialisable snapshot of a single PlanSegment at write time.

    content maps to PlanSegment.steps.
    state is always None — PlanSegment carries no lifecycle state.
    parent_id is supplied by the caller at put() time; not stored on PlanSegment.
    context and metadata are deep-copied at creation to prevent external mutation.
    """
    segment_id: str
    parent_id: Optional[str]
    subgoal_id: str
    state: Optional[str]
    content: List[str]
    created_at: str
    context: Dict[str, Any]
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class SegmentMemorySnapshot:
    """
    Immutable ordered collection of SegmentMemoryRecords.

    records is a tuple to satisfy frozen dataclass requirements.
    Order is deterministic (sorted by created_at, then segment_id).
    """
    records: Tuple[SegmentMemoryRecord, ...]
