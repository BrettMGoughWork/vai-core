from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.agent.memory.types.behavioural_signal_types import BehaviouralSignal


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
    skills: List[str] = field(default_factory=list)

    # --- 2.6.2 Behavioural Observation Layer ---
    # Last executor output (JSON-pure)
    last_output: Optional[Any] = None

    # Previous executor output (JSON-pure)
    previous_output: Optional[Any] = None

    # Structural diff between previous and last output (JSON-pure)
    behavioural_delta: Optional[Dict[str, Any]] = None

    # --- 2.6.3 Behavioural Drift Signals ---
    # Signals emitted by the behavioural drift observation layer.
    # Each signal captures a specific mismatch between declared vs actual execution
    # behaviour (e.g. WRONG_CAPABILITY, WRONG_OUTPUT_SHAPE).
    behavioural_signals: List[BehaviouralSignal] = field(default_factory=list)

    # --- 3.8.8 Skill Result Error ---
    # Error message from a failed skill execution; None if the skill succeeded.
    error: Optional[str] = None

@dataclass(frozen=True)
class SegmentMemorySnapshot:
    """
    Immutable ordered collection of SegmentMemoryRecords.

    records is a tuple to satisfy frozen dataclass requirements.
    Order is deterministic (sorted by created_at, then segment_id).
    """
    records: Tuple[SegmentMemoryRecord, ...]
