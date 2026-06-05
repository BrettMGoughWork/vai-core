from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Literal

from src.core.types.json_pure import ensure_json_pure


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


@dataclass(frozen=True)
class BehaviouralDriftClassification:
    """
    Phase 2.6.4 — Classification produced from a segment's behavioural signals.

    Maps per‑segment BehaviouralSignals into a drift status with confidence.

    drift_status:  ``"no_drift"`` or ``"behavioural_drift"``.
    confidence:    0.0–1.0, computed from signal count and streak.
    reasons:       the BehaviouralSignals that triggered the classification.
    """

    drift_status: Literal["no_drift", "behavioural_drift"]
    confidence: float
    reasons: List[BehaviouralSignal]

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be 0.0–1.0, got {self.confidence}"
            )
        if self.drift_status not in ("no_drift", "behavioural_drift"):
            raise ValueError(
                f"drift_status must be 'no_drift' or 'behavioural_drift', "
                f"got {self.drift_status!r}"
            )
        # Shallow copy of reasons list (signals themselves are frozen)
        object.__setattr__(self, "reasons", list(self.reasons))


# ── Phase 2.6.5 repair actions per signal type ────────────────────────
_SIGNAL_REPAIR_ACTION: dict[BehaviouralSignalType, str] = {
    BehaviouralSignalType.WRONG_CAPABILITY: (
        "verify declared vs executed capability"
    ),
    BehaviouralSignalType.WRONG_OUTPUT_SHAPE: (
        "validate output shape against declared schema"
    ),
    BehaviouralSignalType.WRONG_OUTPUT_SEMANTICS: (
        "inspect semantic fields for correctness"
    ),
    BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT: (
        "audit side-effect declarations vs execution"
    ),
}


@dataclass(frozen=True)
class BehaviouralDriftRepair:
    """
    Phase 2.6.5 — Repair plan produced from a behavioural drift classification.

    Describes how Stratum‑2 interprets and responds to drift.
    Pure, deterministic, JSON‑safe — not an actual code fix.

    needs_repair:    ``True`` when drift is present.
    repair_actions:  human‑readable, JSON‑safe strings describing corrective
                     actions.  Order is deterministic (sorted by signal type).
    confidence:      copied from the classification (0.0–1.0).
    reasons:         the BehaviouralSignals that triggered the repair
                     (defensive copy).
    """

    needs_repair: bool
    repair_actions: List[str]
    confidence: float
    reasons: List[BehaviouralSignal]

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be 0.0–1.0, got {self.confidence}"
            )
        # Defensive copy of mutable containers
        object.__setattr__(self, "repair_actions", list(self.repair_actions))
        object.__setattr__(self, "reasons", list(self.reasons))
