"""
Phase 2.9.3 — Drift Confirmation Engine
========================================

Implements ``confirm_drift()``, a pure, deterministic function that
stabilises drift decisions across cycles using:

- multi‑cycle confirmation (streak thresholds per severity)
- confidence accumulation (current + previous × 0.5)
- drift hysteresis (prevents rapid flip‑flopping between drift / no‑drift)

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
    DriftConfirmationState,
    UnifiedDriftClassification,
)

_CONFIRMATION_THRESHOLDS = {
    "minor": 2,
    "major": 2,
    "catastrophic": 1,
}

_HYSTERESIS_DECAY: float = 0.1
_HYSTERESIS_BOOST: float = 0.2
_PREVIOUS_CONFIDENCE_WEIGHT: float = 0.5


def _compute_streak(
    current: UnifiedDriftClassification,
    previous: Optional[DriftConfirmationState],
) -> int:
    """Compute the streak for the current drift status."""
    if current.status == "no_drift":
        return 0
    if previous is None:
        return 1
    return previous.streak + 1


def _is_confirmed(severity: str, streak: int) -> bool:
    """Check if the drift is confirmed given severity and streak."""
    threshold = _CONFIRMATION_THRESHOLDS[severity]
    return streak >= threshold


def _compute_confidence(
    current: UnifiedDriftClassification,
    previous: Optional[DriftConfirmationState],
) -> float:
    """Accumulate confidence: current + previous × 0.5, capped at 1.0."""
    accumulated = current.confidence
    if previous is not None:
        accumulated += previous.confidence * _PREVIOUS_CONFIDENCE_WEIGHT
    return min(1.0, accumulated)


def _compute_hysteresis(
    previous: Optional[DriftConfirmationState],
    confirmed: bool,
) -> float:
    """
    Compute hysteresis value.

    - Start by decaying previous hysteresis by HYSTERESIS_DECAY.
    - If drift is confirmed, boost by HYSTERESIS_BOOST.
    - Clamp to [0.0, 1.0].
    """
    if previous is not None:
        value = max(0.0, previous.hysteresis - _HYSTERESIS_DECAY)
    else:
        value = 0.0

    if confirmed:
        value = min(1.0, value + _HYSTERESIS_BOOST)

    return value


def confirm_drift(
    current: UnifiedDriftClassification,
    previous: Optional[DriftConfirmationState] = None,
) -> DriftConfirmationState:
    """
    Stabilise drift decisions across cycles.

    Parameters
    ----------
    current:
        The current cycle's unified drift classification.
    previous:
        The previous cycle's confirmation state, or ``None`` on first call.

    Returns
    -------
    DriftConfirmationState
        A frozen, JSON‑safe state with confirmed flag, severity, accumulated
        confidence, streak, hysteresis, and history.
    """
    # ── 1. Multi‑cycle confirmation ──────────────────────────────────────
    streak = _compute_streak(current, previous)

    if current.status == "no_drift":
        confirmed = False
    else:
        confirmed = _is_confirmed(current.severity, streak)

    # ── 2. Confidence accumulation ───────────────────────────────────────
    confidence = _compute_confidence(current, previous)

    # ── 3. Drift hysteresis ──────────────────────────────────────────────
    hysteresis = _compute_hysteresis(previous, confirmed)

    # Suppress drift when current confidence is below the hysteresis
    # threshold — prevents rapid flip‑flopping.
    if current.confidence < hysteresis:
        confirmed = False

    # ── 4. Severity propagation ──────────────────────────────────────────
    severity = current.severity if confirmed else "minor"

    # ── 5. History tracking ──────────────────────────────────────────────
    history: List[UnifiedDriftClassification]
    if previous is not None:
        history = list(previous.history)
    else:
        history = []
    history.append(current)

    return DriftConfirmationState(
        confirmed=confirmed,
        severity=severity,
        confidence=confidence,
        streak=streak,
        hysteresis=hysteresis,
        history=history,
    )
