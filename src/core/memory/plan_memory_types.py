from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class PlanMemoryRecord:
    """
    Pure, JSON-serialisable snapshot of a single Plan at write time.

    plan_id, subgoal_id, segments, created_at, and metadata are caller-supplied
    at put() time — Plan carries none of these fields itself.
    Plan fields (intent, targetskillid, arguments, reasoning_summary) are stored
    here for full round-trip reconstruction.
    arguments is deep-copied at creation to prevent external mutation.
    """
    plan_id: str
    subgoal_id: str
    segments: List[str]
    created_at: str
    metadata: Dict[str, Any]
    intent: str
    targetskillid: str
    arguments: Dict[str, Any]
    reasoning_summary: str


@dataclass(frozen=True)
class PlanMemorySnapshot:
    """
    Immutable ordered collection of PlanMemoryRecords.

    records is a tuple to satisfy frozen dataclass requirements.
    Order is deterministic (sorted by created_at, then plan_id).
    """
    records: Tuple[PlanMemoryRecord, ...]
