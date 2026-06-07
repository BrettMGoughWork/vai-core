from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any
import time

from src.core.types.json_pure import ensure_json_pure


# ---------------------------------------------------------------------------
# 2.3.x — Existing signal types
# ---------------------------------------------------------------------------

class SignalType(str, Enum):
    DRIFT = "drift"
    STUCK = "stuck"
    UNSAFE = "unsafe"
    BEHAVIOURAL_SHAPE_MISMATCH = "behavioural_shape_mismatch"


class SignalSeverity(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class SignalSource(str, Enum):
    """
    Named signal sources for the execution‑lifecycle drift framework (2.3.8).
    Extended in 2.6.x to include behavioural execution mismatch signals.
    """

    # Existing sources
    PLANNING_DEVIATION = "planning_deviation"
    LOOP_ANOMALY = "loop_anomaly"
    SUBGOAL_STALL = "subgoal_stall"
    COGNITIVE_DISSONANCE = "cognitive_dissonance"
    EXECUTION_MISMATCH = "execution_mismatch"

    # -----------------------------------------------------------------------
    # 2.6.1 — Behavioural drift sources
    # -----------------------------------------------------------------------
    BEHAVIOURAL_SHAPE_MISMATCH = "behavioural_shape_mismatch"
    BEHAVIOURAL_TYPE_MISMATCH = "behavioural_type_mismatch"
    BEHAVIOURAL_UNEXPECTED = "behavioural_unexpected_output"


# ---------------------------------------------------------------------------
# Signal weighting (used later in 2.9 unified drift engine)
# ---------------------------------------------------------------------------

DEFAULT_SIGNAL_WEIGHT = 0.5

SIGNAL_WEIGHTS: Dict[str, float] = {
    # Named execution‑lifecycle sources
    SignalSource.PLANNING_DEVIATION: 0.80,
    SignalSource.LOOP_ANOMALY: 0.70,
    SignalSource.SUBGOAL_STALL: 0.60,
    SignalSource.COGNITIVE_DISSONANCE: 0.90,
    SignalSource.EXECUTION_MISMATCH: 0.85,

    # 2.6.1 — Behavioural drift weights
    SignalSource.BEHAVIOURAL_SHAPE_MISMATCH: 0.75,
    SignalSource.BEHAVIOURAL_TYPE_MISMATCH: 0.70,
    SignalSource.BEHAVIOURAL_UNEXPECTED: 0.65,

    # Legacy sources (existing emitters)
    "segments": 0.70,
    "subgoals": 0.60,
    "runtime": 0.90,
}


# ---------------------------------------------------------------------------
# GovernedSignal — unchanged contract, extended payload semantics
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GovernedSignal:
    """
    Immutable, JSON‑pure signal emitted by deterministic substrate checks.
    Consumed by 2.5.x reflection, repair, and recovery layers.

    2.6.x extends usage to behavioural drift signals emitted when executor
    output does not match expected capability shape/type.
    """

    signal_type: SignalType
    severity: SignalSeverity
    confidence: float # 0.0 → 1.0
    source: str # e.g. "subgoals", "segments", "runtime", or a SignalSource value
    payload: Dict[str, Any]

    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))

    def __post_init__(self):
        ensure_json_pure(self.payload)