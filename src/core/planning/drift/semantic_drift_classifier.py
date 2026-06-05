"""
Phase 2.8.3 — Semantic Drift Classifier
=======================================

Maps a list of ``SemanticDriftSignal``\\ s (emitted by the 2.8.2 detector)
into a ``SemanticDriftClassification`` that summarises the semantic health
of a segment across cycles.

The classifier is **pure** and **deterministic**:

- No LLM calls, no tool calls, no I/O.
- Does not mutate inputs (signals, previous classification).
- Multi‑cycle confirmation is tracked via the ``streak`` field on the
  classification itself (not from segment metadata).

Confidence formula
------------------

::

    base_confidence = max(s.confidence for s in signals)
    streak_bonus    = 0.1 * streak
    confidence      = min(1.0, base_confidence + streak_bonus)

Streak logic
------------
- First cycle (``previous is None``) → streak = 1.
- Same status as previous classification → streak = previous.streak + 1.
- Different status → streak = 1 (reset).
"""
from __future__ import annotations

from typing import List, Optional

from src.core.planning.drift.semantic_signal_types import (
    SemanticDriftClassification,
    SemanticDriftSignal,
)

# ── constants ────────────────────────────────────────────────────────────────

_STREAK_MULTIPLIER: float = 0.1  # bonus per consecutive matching cycle


# ── public API ───────────────────────────────────────────────────────────────


def classify_semantic_drift(
    signals: List[SemanticDriftSignal],
    previous: Optional[SemanticDriftClassification] = None,
) -> SemanticDriftClassification:
    """
    Classify semantic drift for a segment across cycles.

    Args:
        signals:
            Semantic drift signals from the 2.8.2 emitter.
        previous:
            The classification from the previous cycle, or ``None`` on the
            first cycle.

    Returns:
        A ``SemanticDriftClassification`` with status, categories,
        confidence, reasons, and streak.
    """
    # ── no signals → no drift ────────────────────────────────────────────
    if not signals:
        return SemanticDriftClassification(
            status="no_drift",
            categories=[],
            confidence=0.0,
            reasons=[],
            streak=0,
        )

    # ── derive categories (sorted deterministically, unique) ──────────────
    categories = sorted({s.type for s in signals})

    # ── compute confidence ───────────────────────────────────────────────
    base_confidence = max(s.confidence for s in signals)

    # ── compute streak ───────────────────────────────────────────────────
    current_status: str = "semantic_drift"
    if previous is None:
        streak = 1
    elif previous.status == current_status:
        streak = previous.streak + 1
    else:
        streak = 1

    streak_bonus = _STREAK_MULTIPLIER * streak
    confidence = min(1.0, base_confidence + streak_bonus)

    # Round to avoid floating‑point noise
    confidence = round(confidence, 10)

    return SemanticDriftClassification(
        status="semantic_drift",
        categories=categories,
        confidence=confidence,
        reasons=list(signals),  # defensive copy
        streak=streak,
    )
