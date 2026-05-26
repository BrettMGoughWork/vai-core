from __future__ import annotations

from typing import Optional, Dict, Any

from src.core.signals.model import (
    GovernedSignal,
    SignalType,
    SignalSeverity,
)


# ------------------------------------------------------------
# Thresholds (deterministic, no heuristics)
# ------------------------------------------------------------
MAX_SEGMENT_FAILURES = 3
MAX_IDLE_CYCLES = 5
MAX_UNSAFE_EVENTS = 1


# ------------------------------------------------------------
# Drift classification
# ------------------------------------------------------------
def classify_drift(
    *,
    repeated_failures: int = 0,
    gaps: int = 0,
    overlaps: int = 0,
) -> Optional[GovernedSignal]:

    if repeated_failures > MAX_SEGMENT_FAILURES:
        return GovernedSignal(
            signal_type=SignalType.DRIFT,
            severity=SignalSeverity.CRITICAL,
            confidence=0.9,
            source="segments",
            payload={"repeated_failures": repeated_failures},
        )

    if gaps > 0 or overlaps > 0:
        return GovernedSignal(
            signal_type=SignalType.DRIFT,
            severity=SignalSeverity.WARN,
            confidence=0.7,
            source="segments",
            payload={"gaps": gaps, "overlaps": overlaps},
        )

    return None


# ------------------------------------------------------------
# Stuck classification
# ------------------------------------------------------------
def classify_stuck(
    *,
    idle_cycles: int = 0,
    leaf_id: str,
    parent_id: str,
) -> Optional[GovernedSignal]:

    if idle_cycles > MAX_IDLE_CYCLES:
        return GovernedSignal(
            signal_type=SignalType.STUCK,
            severity=SignalSeverity.WARN,
            confidence=0.6,
            source="subgoals",
            payload={
                "leaf_subgoal_id": leaf_id,
                "parent_subgoal_id": parent_id,
                "idle_cycles": idle_cycles,
            },
        )

    return None


# ------------------------------------------------------------
# Unsafe classification
# ------------------------------------------------------------
def classify_unsafe(
    *,
    unsafe_events: int = 0,
    conditions: Dict[str, Any],
) -> Optional[GovernedSignal]:

    if unsafe_events >= MAX_UNSAFE_EVENTS:
        return GovernedSignal(
            signal_type=SignalType.UNSAFE,
            severity=SignalSeverity.CRITICAL,
            confidence=1.0,
            source="runtime",
            payload={"conditions": conditions},
        )

    return None