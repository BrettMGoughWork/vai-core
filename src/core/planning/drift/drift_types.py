from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from src.core.signals.model import GovernedSignal, SignalSeverity
from src.core.types.json_pure import ensure_json_pure


class DriftRecoveryAction(str, Enum):
    NONE          = "none"
    RESET_SUBGOAL = "reset_subgoal"
    REPLAN        = "replan"
    ABORT         = "abort"


@dataclass(frozen=True)
class StepContext:
    """
    Lightweight execution context passed to the drift detector.

    step_id:   identifies the reasoning step being evaluated.
    signals:   governed signals observed during this step.
    timestamp: logical anchor (ms) used for recency weighting — must be >= any signal timestamp.
    """
    step_id: str
    signals: Tuple[GovernedSignal, ...]
    timestamp: int


@dataclass(frozen=True)
class DriftReport:
    """
    Immutable result of a drift detection pass.

    signal:             primary trigger signal (highest contribution), or None if no signals.
    confidence:         aggregate drift confidence in [0.0, 1.0].
    severity:           INFO / WARN / CRITICAL derived from confidence bands.
    recommended_action: recovery action derived from confidence thresholds.
    """
    signal: Optional[GovernedSignal]
    confidence: float
    severity: SignalSeverity
    recommended_action: DriftRecoveryAction


# ---------------------------------------------------------------------------
# Phase 2.5.3 — Full Drift Detection types
# ---------------------------------------------------------------------------

class DriftSignalClass(str, Enum):
    """The three orthogonal signal dimensions that feed FullDriftDetector."""
    STRUCTURAL  = "structural"
    BEHAVIOURAL = "behavioural"
    TEMPORAL    = "temporal"


class DriftClassification(str, Enum):
    """
    Ordered drift severity tiers.  Derived deterministically from signal score.
    NO_DRIFT → MINOR → MODERATE → SEVERE → CRITICAL.
    """
    NO_DRIFT       = "no_drift"
    MINOR_DRIFT    = "minor_drift"
    MODERATE_DRIFT = "moderate_drift"
    SEVERE_DRIFT   = "severe_drift"
    CRITICAL_DRIFT = "critical_drift"


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


@dataclass(frozen=True)
class DriftConfirmation:
    """
    Result of a multi-cycle confirmation pass.

    confirmed:       True when signals have persisted for >= confirmation_cycles.
    confidence:      Decay-weighted aggregate confidence in [0.0, 1.0].
    cycles_observed: Number of cycles that have accumulated signals so far.
    signals:         All signals from the current confirmed window (oldest-first).
    history:         Per-cycle signal lists (oldest-first tuple of tuples).
                     NOTE: history contains tuples — do not pass to stable_hash.
    """
    confirmed: bool
    confidence: float
    cycles_observed: int
    signals: Tuple[DriftSignal, ...]
    history: Tuple[Tuple[DriftSignal, ...], ...]


@dataclass(frozen=True)
class DriftTrigger:
    """
    Produced when drift is confirmed.  Consumed by PlanRepair (2.5.1).

    All fields are JSON-serialisable scalars and dicts.
    classification is a DriftClassification value string.
    """
    classification: str
    confidence: float
    cycles_observed: int
    structural_context: Dict[str, Any]
    behavioural_context: Dict[str, Any]
    temporal_context: Dict[str, Any]
