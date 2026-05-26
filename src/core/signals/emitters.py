from __future__ import annotations

from typing import List
from src.core.signals.model import GovernedSignal, SignalType, SignalSeverity
from src.core.planning.subgoals.state import SubgoalState
from src.core.planning.segments.state import SegmentState


# ------------------------------------------------------------
# Subgoal-based signals
# ------------------------------------------------------------
def emit_stuck_from_subgoals(state: SubgoalState) -> List[GovernedSignal]:
    """
    Emits a STUCK signal when the active chain shows no forward progress.
    This is a pure substrate check: no heuristics, no side effects.
    """
    signals: List[GovernedSignal] = []

    active_chain = state.active_chain()
    if len(active_chain) <= 1:
        return signals

    leaf = active_chain[-1]
    parent = active_chain[-2]

    # Simple deterministic stuck rule:
    # If the leaf has been active longer than its parent, or
    # if the leaf has no children and hasn't transitioned.
    if leaf.created_at < parent.created_at:
        signals.append(
            GovernedSignal(
                signal_type=SignalType.STUCK,
                severity=SignalSeverity.WARN,
                confidence=0.6,
                source="subgoals",
                payload={
                    "leaf_subgoal_id": leaf.subgoal_id,
                    "parent_subgoal_id": parent.subgoal_id,
                },
            )
        )

    return signals


# ------------------------------------------------------------
# Segment-based signals
# ------------------------------------------------------------
def emit_drift_from_segments(state: SegmentState) -> List[GovernedSignal]:
    """
    Emits a DRIFT signal when segment stitching or ordering suggests deviation.
    """
    signals: List[GovernedSignal] = []

    if state.has_gaps or state.has_overlaps:
        signals.append(
            GovernedSignal(
                signal_type=SignalType.DRIFT,
                severity=SignalSeverity.WARN,
                confidence=0.7,
                source="segments",
                payload={
                    "gaps": len(state.gaps),
                    "overlaps": len(state.overlaps),
                },
            )
        )

    if state.repeated_failures > 3:
        signals.append(
            GovernedSignal(
                signal_type=SignalType.DRIFT,
                severity=SignalSeverity.CRITICAL,
                confidence=0.9,
                source="segments",
                payload={
                    "repeated_failures": state.repeated_failures,
                },
            )
        )

    return signals


# ------------------------------------------------------------
# Runtime-based signals (unsafe)
# ------------------------------------------------------------
def emit_unsafe_from_runtime(runtime_state) -> List[GovernedSignal]:
    """
    Emits UNSAFE signals based on runtime substrate conditions.
    Placeholder until runtime invariants are defined.
    """
    signals: List[GovernedSignal] = []

    if getattr(runtime_state, "unsafe_conditions", None):
        signals.append(
            GovernedSignal(
                signal_type=SignalType.UNSAFE,
                severity=SignalSeverity.CRITICAL,
                confidence=1.0,
                source="runtime",
                payload={
                    "conditions": runtime_state.unsafe_conditions,
                },
            )
        )

    return signals