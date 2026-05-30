from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any
import time

from src.core.types.json_pure import ensure_json_pure


class SignalType(str, Enum):
    DRIFT = "drift"
    STUCK = "stuck"
    UNSAFE = "unsafe"


class SignalSeverity(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class SignalSource(str, Enum):
    """Named signal sources for the execution-lifecycle drift framework (2.3.8)."""
    PLANNING_DEVIATION   = "planning_deviation"
    LOOP_ANOMALY         = "loop_anomaly"
    SUBGOAL_STALL        = "subgoal_stall"
    COGNITIVE_DISSONANCE = "cognitive_dissonance"
    EXECUTION_MISMATCH   = "execution_mismatch"


# Source → weight mapping. Unknown sources fall back to DEFAULT_SIGNAL_WEIGHT.
# Includes legacy emitter sources for backward compatibility.
DEFAULT_SIGNAL_WEIGHT = 0.5

SIGNAL_WEIGHTS: Dict[str, float] = {
    # Named execution-lifecycle sources
    SignalSource.PLANNING_DEVIATION:   0.80,
    SignalSource.LOOP_ANOMALY:         0.70,
    SignalSource.SUBGOAL_STALL:        0.60,
    SignalSource.COGNITIVE_DISSONANCE: 0.90,
    SignalSource.EXECUTION_MISMATCH:   0.85,
    # Legacy sources (existing emitters)
    "segments": 0.70,
    "subgoals": 0.60,
    "runtime":  0.90,
}


@dataclass(frozen=True)
class GovernedSignal:
    """
    Immutable, JSON‑pure signal emitted by deterministic substrate checks.
    Consumed by 2.5.x reflection, repair, and recovery layers.
    """

    signal_type: SignalType
    severity: SignalSeverity
    confidence: float # 0.0 → 1.0
    source: str # e.g. "subgoals", "segments", "runtime", or a SignalSource value
    payload: Dict[str, Any]

    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))

    def __post_init__(self):
        ensure_json_pure(self.payload)
