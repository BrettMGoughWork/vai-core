from __future__ import annotations

from typing import List, Optional

from src.core.signals.model import GovernedSignal
from src.core.signals.emitters import (
    emit_stuck_from_subgoals,
    emit_drift_from_segments,
    emit_unsafe_from_runtime,
)
from src.core.signals.classifier import (
    classify_drift,
    classify_stuck,
    classify_unsafe,
)

from src.core.planning.subgoals.state import SubgoalState
from src.core.planning.segments.state import SegmentState


def evaluate_signals(
    subgoal_state: SubgoalState,
    segment_state: SegmentState,
    runtime_state: Optional[object] = None,
) -> List[GovernedSignal]:
    """
    Unified substrate-level signal evaluation.
    Deterministic, JSON-pure, and consumed by 2.5.x reflection/repair.
    """

    signals: List[GovernedSignal] = []

    # ------------------------------------------------------------
    # Subgoal-based signals (STUCK)
    # ------------------------------------------------------------
    raw_stuck = emit_stuck_from_subgoals(subgoal_state)
    for s in raw_stuck:
        classified = classify_stuck(
            idle_cycles=subgoal_state.idle_cycles,
            leaf_id=s.payload.get("leaf_subgoal_id"),
            parent_id=s.payload.get("parent_subgoal_id"),
        )
        if classified:
            signals.append(classified)

    # ------------------------------------------------------------
    # Segment-based signals (DRIFT)
    # ------------------------------------------------------------
    raw_drift = emit_drift_from_segments(segment_state)
    for s in raw_drift:
        classified = classify_drift(
            repeated_failures=int(s.payload.get("repeated_failures", 0) or 0),
            gaps=int(s.payload.get("gaps", 0) or 0),
            overlaps=int(s.payload.get("overlaps", 0) or 0),
        )
        if classified:
            signals.append(classified)

    # ------------------------------------------------------------
    # Runtime-based signals (UNSAFE)
    # ------------------------------------------------------------
    if runtime_state is not None:
        raw_unsafe = emit_unsafe_from_runtime(runtime_state)
        for s in raw_unsafe:
            classified = classify_unsafe(
                unsafe_events=len(getattr(runtime_state, "unsafe_conditions", [])),
                conditions=s.payload.get("conditions", {}),
            )
            if classified:
                signals.append(classified)

    return signals