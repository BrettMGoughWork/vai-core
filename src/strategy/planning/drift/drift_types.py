from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

from src.strategy.types.json_pure import ensure_json_pure


class DriftSignalClass(str, Enum):
    """The three orthogonal signal dimensions that feed drift detection."""
    STRUCTURAL  = "structural"
    BEHAVIOURAL = "behavioural"
    TEMPORAL    = "temporal"


@dataclass(frozen=True)
class DriftSignal:
    """
    A single drift observation produced by a signal-collector function.

    JSON-serialisable; metadata must be JSON-pure.
    signal_class must be a DriftSignalClass value string.
    severity must be "low" | "medium" | "high".
    timestamp is an ISO 8601 string anchored to the detection cycle.
    """
    type: str
    severity: str
    timestamp: str
    signal_class: str
    metadata: Dict[str, Any]

    def __post_init__(self) -> None:
        if self.severity not in ("low", "medium", "high"):
            raise ValueError(f"severity must be low/medium/high, got {self.severity!r}")
        valid_classes = {c.value for c in DriftSignalClass}
        if self.signal_class not in valid_classes:
            raise ValueError(
                f"signal_class must be one of {valid_classes}, got {self.signal_class!r}"
            )
        ensure_json_pure(self.metadata)
        object.__setattr__(self, "metadata", copy.deepcopy(self.metadata))
