"""
Phase 2.9.2 — Unified Drift Classifier
======================================

Implements ``classify_unified_drift()``, a pure, deterministic function that
converts a list of ``UnifiedDriftSignal`` instances into a
``UnifiedDriftClassification`` with severity levels and multi‑cycle streak
tracking.

Invariants
----------
- Pure — no side effects, no mutation of inputs.
- Deterministic — identical inputs always produce identical outputs.
- JSON‑safe — all outputs are serialisable to JSON.
- No LLM calls, no imports outside stdlib.
"""
from __future__ import annotations

from typing import List, Optional

from src.core.planning.drift.unified_drift_types import (
    UnifiedDriftClassification,
    UnifiedDriftSignal,
)

_STREAK_BONUS: float = 0.1


def _compute_severity(max_weight: float) -> str:
    """Map max signal weight to a severity label."""
    if max_weight >= 0.75:
        return "catastrophic"
    elif max_weight >= 0.40:
        return "major"
    else:
        return "minor"


def _compute_confidence(
    signals: List[UnifiedDriftSignal],
    streak: int,
) -> float:
    """
    Compute classification confidence from signal weights, decay, and streak.

    confidence = min(1.0, base_confidence × decay_penalty + streak_bonus)
    """
    if not signals:
        return 0.0

    base_confidence = max(s.weight for s in signals)
    decay_penalty = sum(s.decay for s in signals) / len(signals)
    streak_bonus = _STREAK_BONUS * streak

    raw = base_confidence * decay_penalty + streak_bonus
    return min(1.0, raw)


def classify_unified_drift(
    signals: List[UnifiedDriftSignal],
    previous: Optional[UnifiedDriftClassification] = None,
) -> UnifiedDriftClassification:
    """
    Convert unified drift signals into a deterministic classification.

    Parameters
    ----------
    signals:
        The list of ``UnifiedDriftSignal`` instances from the current cycle.
    previous:
        The classification from the previous cycle, or ``None`` on the first
        cycle.  Used to compute the multi‑cycle streak.

    Returns
    -------
    UnifiedDriftClassification
        A frozen, JSON‑safe classification with status, severity, categories,
        confidence, reasons, and streak.
    """
    # ── No‑drift path ────────────────────────────────────────────────────
    if not signals:
        return UnifiedDriftClassification(
            status="no_drift",
            severity="minor",
            categories=[],
            confidence=0.0,
            reasons=[],
            streak=0,
        )

    # ── Drift‑detected path ──────────────────────────────────────────────
    status = "drift_detected"

    # Streak logic
    if previous is None:
        streak = 1
    elif previous.status == status:
        streak = previous.streak + 1
    else:
        streak = 1

    # Categories: sorted unique signal types
    categories = sorted({s.type for s in signals})

    # Confidence
    confidence = _compute_confidence(signals, streak)

    # Severity
    max_weight = max(s.weight for s in signals)
    severity = _compute_severity(max_weight)

    return UnifiedDriftClassification(
        status=status,
        severity=severity,
        categories=categories,
        confidence=confidence,
        reasons=list(signals),
        streak=streak,
    )
