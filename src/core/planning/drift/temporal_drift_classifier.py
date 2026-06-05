"""
Phase 2.7.3 — Temporal Drift Classifier
=======================================

Maps a list of ``TemporalDriftSignal``\\ s (emitted by the 2.7.2 detectors)
into a ``TemporalDriftClassification`` that summarises the temporal health
of a segment across cycles.

The classifier is **pure** and **deterministic**:

- No LLM calls, no tool calls, no I/O.
- Does not mutate inputs (signals, previous classification).
- Multi‑cycle confirmation is tracked via the ``streak`` field on the
  classification itself (not from segment metadata).

Category mapping
----------------
- ``no_progress`` → ``"stall"``
- ``repetition`` → ``"repetition"``
- ``oscillation`` → ``"oscillation"``
- ``regression`` → ``"regression"``

Confidence formula
------------------

::

    base_confidence = max(s.confidence for s in signals)
    streak_bonus    = 0.1 * streak
    confidence      = min(1.0, base_confidence + streak_bonus)

Streak logic
------------
- First cycle (``previous_classification is None``) → streak = 1.
- Same status as previous classification → streak = previous.streak + 1.
- Different status → streak = 1 (reset).
"""
from __future__ import annotations

from typing import List, Optional

from src.core.planning.drift.temporal_signal_types import (
    TemporalDriftClassification,
    TemporalDriftSignal,
)

# ── constants ────────────────────────────────────────────────────────────────

_STREAK_MULTIPLIER: float = 0.1  # bonus per consecutive matching cycle

_SIGNAL_TO_CATEGORY: dict[str, str] = {
    "no_progress": "stall",
    "repetition": "repetition",
    "oscillation": "oscillation",
    "regression": "regression",
}


# ── public API ───────────────────────────────────────────────────────────────


def classify_temporal_drift(
    signals: List[TemporalDriftSignal],
    previous_classification: Optional[TemporalDriftClassification] = None,
) -> TemporalDriftClassification:
    """
    Classify temporal drift for a segment across cycles.

    Args:
        signals:
            Temporal drift signals from the 2.7.2 detector.
        previous_classification:
            The classification from the previous cycle, or ``None`` on the
            first cycle.

    Returns:
        A ``TemporalDriftClassification`` with status, categories,
        confidence, reasons, and streak.
    """
    # ── no signals → no drift ────────────────────────────────────────────
    if not signals:
        return TemporalDriftClassification(
            status="no_drift",
            categories=[],
            confidence=0.0,
            reasons=[],
            streak=0,
        )

    # ── derive categories (sorted deterministically) ─────────────────────
    categories = sorted(
        {_SIGNAL_TO_CATEGORY[s.type] for s in signals}
    )

    # ── compute confidence ───────────────────────────────────────────────
    base_confidence = max(s.confidence for s in signals)

    # ── compute streak ───────────────────────────────────────────────────
    current_status: str = "temporal_drift"
    if previous_classification is None:
        streak = 1
    elif previous_classification.status == current_status:
        streak = previous_classification.streak + 1
    else:
        streak = 1

    streak_bonus = _STREAK_MULTIPLIER * streak
    confidence = min(1.0, base_confidence + streak_bonus)

    # Round to avoid floating‑point noise
    confidence = round(confidence, 10)

    return TemporalDriftClassification(
        status="temporal_drift",
        categories=categories,
        confidence=confidence,
        reasons=list(signals),  # defensive copy
        streak=streak,
    )
