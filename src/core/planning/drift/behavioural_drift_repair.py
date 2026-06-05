"""
Phase 2.6.5 — Behavioural Drift Repair
======================================

Produces a ``BehaviouralDriftRepair`` object that describes how Stratum‑2
interprets and responds to behavioural drift detected in a single segment.

The repair engine is **pure** and **deterministic**:

- Reads the ``BehaviouralDriftClassification`` produced by 2.6.4.
- Generates a structured repair plan (human‑readable action strings).
- Never mutates the ``SegmentMemoryRecord``, its signals, or its metadata.
- No LLM calls, no tool calls, no I/O.

Repair actions are derived from the signal types in the classification:

===================================== ===========================================
``WRONG_CAPABILITY``                  ``verify declared vs executed capability``
``WRONG_OUTPUT_SHAPE``                ``validate output shape against declared
                                      schema``
``WRONG_OUTPUT_SEMANTICS``            ``inspect semantic fields for correctness``
``UNEXPECTED_SIDE_EFFECT``            ``audit side-effect declarations vs
                                      execution``
===================================== ===========================================

When multiple signals are present, actions are sorted alphabetically by
signal type name for deterministic output.
"""
from __future__ import annotations

from typing import List

from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.drift.behavioural_signal_types import (
    _SIGNAL_REPAIR_ACTION,
    BehaviouralDriftClassification,
    BehaviouralDriftRepair,
    BehaviouralSignal,
    BehaviouralSignalType,
)


def repair_behavioural_drift(
    record: SegmentMemoryRecord,
    classification: BehaviouralDriftClassification,
) -> BehaviouralDriftRepair:
    """
    Generate a repair plan from a behavioural drift classification.

    Args:
        record:         the segment record (read‑only; never mutated).
        classification: the classification produced by
                        ``classify_behavioural_drift()``.

    Returns:
        A ``BehaviouralDriftRepair`` with ``needs_repair``, sorted action
        strings, confidence, and defensive copy of reasons.
    """
    # ── no drift → no repair ──────────────────────────────────────────
    if classification.drift_status == "no_drift":
        return BehaviouralDriftRepair(
            needs_repair=False,
            repair_actions=[],
            confidence=classification.confidence,
            reasons=list(classification.reasons),
        )

    # ── derive actions from signals ────────────────────────────────────
    seen: set[BehaviouralSignalType] = set()
    actions: List[str] = []

    for signal in classification.reasons:
        st = signal.signal_type
        if st not in seen and st in _SIGNAL_REPAIR_ACTION:
            seen.add(st)
            actions.append(_SIGNAL_REPAIR_ACTION[st])

    # Deterministic ordering: sort by signal type name
    actions.sort()

    return BehaviouralDriftRepair(
        needs_repair=True,
        repair_actions=actions,
        confidence=classification.confidence,
        reasons=list(classification.reasons),
    )
