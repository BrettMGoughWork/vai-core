from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class SubgoalMemoryRecord:
    """
    Pure, JSON-serialisable snapshot of a single Subgoal at write time.

    state is stored as a string value (not an enum) to keep the record
    independent of SubgoalLifecycleState imports and JSON-pure by construction.
    context and metadata are deep-copied at creation to prevent external mutation.
    """
    subgoal_id: str
    parent_id: Optional[str]
    state: str
    goal: str
    context: Dict[str, Any]
    metadata: Dict[str, Any]
    created_at: int


@dataclass(frozen=True)
class SubgoalMemorySnapshot:
    """
    Immutable ordered collection of SubgoalMemoryRecords.

    records is a tuple to satisfy frozen dataclass requirements.
    Order is deterministic (sorted by created_at, then subgoal_id).
    """
    records: Tuple[SubgoalMemoryRecord, ...]
