from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.agent.memory.types.json_pure import ensure_json_pure


@dataclass(frozen=True)
class DriftEvent:
    """
    Pure, JSON-serialisable record of a single drift observation.

    timestamp:   logical ms anchor — consistent with GovernedSignal/StepContext.
    subgoal_id:  subgoal being evaluated when drift was detected.
    segment_id:  optional segment context (None if not applicable).
    step_id:     optional step context (None if not applicable).
    signal_type: string discriminator for the kind of drift signal observed.
                 Callers should use a meaningful value (e.g. a SignalSource string)
                 rather than the top-level GovernedSignal.signal_type ("drift"),
                 which does not vary across events.
    confidence:  aggregate drift confidence in [0.0, 1.0].
    details:     arbitrary JSON-pure payload; deep-copied on construction.
    """
    timestamp: int
    subgoal_id: str
    segment_id: Optional[str]
    step_id: Optional[str]
    signal_type: str
    confidence: float
    details: Dict[str, Any]

    def __post_init__(self) -> None:
        if self.timestamp < 0:
            raise ValueError(f"timestamp must be >= 0, got {self.timestamp}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")
        if not self.subgoal_id:
            raise ValueError("subgoal_id must be non-empty")
        ensure_json_pure(self.details)
        # Deep-copy to prevent external mutation of the stored dict
        object.__setattr__(self, "details", copy.deepcopy(self.details))


@dataclass(frozen=True)
class DriftMemorySnapshot:
    """
    Immutable ordered collection of DriftEvents.

    events is a tuple to satisfy frozen dataclass requirements.
    Order reflects insertion order (oldest first).
    """
    events: Tuple[DriftEvent, ...]
