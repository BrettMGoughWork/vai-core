from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from src.core.signals.model import GovernedSignal, SignalSeverity


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
