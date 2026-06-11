from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

from src.strategy.types.json_pure import ensure_json_pure


class BehaviouralSignalType(str, Enum):
    """Phase 2.6.3 — Behavioural drift signal types emitted by Stratum-2 observation."""

    WRONG_CAPABILITY = "wrong_capability"
    WRONG_OUTPUT_SHAPE = "wrong_output_shape"
    WRONG_OUTPUT_SEMANTICS = "wrong_output_semantics"
    UNEXPECTED_SIDE_EFFECT = "unexpected_side_effect"


@dataclass(frozen=True)
class BehaviouralSignal:
    """
    A single behavioural drift signal produced by the 2.6.3 observation layer.

    Attached to SegmentMemoryRecord.behavioural_signals.
    Pure, deterministic, JSON-serialisable.

    signal_type:  one of BehaviouralSignalType.
    segment_id:   the segment record this signal belongs to.
    subgoal_id:   the subgoal this segment is associated with.
    details:      JSON-pure dict of contextual information (e.g. declared vs actual capability).
    timestamp:    ISO 8601 string anchored to the detection cycle.
    """

    signal_type: BehaviouralSignalType
    segment_id: str
    subgoal_id: str
    details: Dict[str, Any]
    timestamp: str

    def __post_init__(self) -> None:
        ensure_json_pure(self.details)
        object.__setattr__(self, "details", copy.deepcopy(self.details))
