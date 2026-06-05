"""
Phase 2.9.5 — Drift Trace Builder
==================================

Constructs a ``DriftTrace`` from unified drift classification (2.9.2),
drift confirmation state (2.9.3), drift recovery decision (2.9.4), and an
optional previous trace for history appending.

The trace is **pure**, **deterministic**, and never mutates its inputs.

Trace Components
----------------
unified_drift_history
    Appends the current ``UnifiedDriftClassification`` as a JSON‑safe summary
    dict with ``status``, ``severity``, ``categories``, ``confidence``, and
    ``streak`` to the previous trace's history.

drift_confidence_evolution
    Appends ``DriftConfirmationState.confidence`` to the previous trace's
    confidence evolution list.

drift_recovery_decisions
    Appends the current ``DriftRecoveryDecision`` as a JSON‑safe summary
    dict with ``action``, ``severity``, ``confidence``, ``streak``, and
    ``hysteresis`` to the previous trace's history.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.planning.drift.segment_trace_types import DriftTrace
from src.core.planning.drift.unified_drift_types import (
    DriftConfirmationState,
    DriftRecoveryDecision,
    UnifiedDriftClassification,
)


# ── classification summary ───────────────────────────────────────────────────


def _build_classification_summary(
    classification: UnifiedDriftClassification,
) -> Dict[str, Any]:
    """Convert a ``UnifiedDriftClassification`` into a JSON‑safe summary dict."""
    return {
        "status": classification.status,
        "severity": classification.severity,
        "categories": list(classification.categories),
        "confidence": classification.confidence,
        "streak": classification.streak,
    }


# ── recovery decision summary ────────────────────────────────────────────────


def _build_recovery_summary(
    decision: DriftRecoveryDecision,
) -> Dict[str, Any]:
    """Convert a ``DriftRecoveryDecision`` into a JSON‑safe summary dict."""
    return {
        "action": decision.action,
        "severity": decision.severity,
        "confidence": decision.confidence,
        "streak": decision.streak,
        "hysteresis": decision.hysteresis,
    }


# ── history builders ─────────────────────────────────────────────────────────


def _build_unified_drift_history(
    classification: UnifiedDriftClassification,
    previous_trace: Optional[DriftTrace],
) -> List[Dict[str, Any]]:
    """Append the current classification summary to the previous trace's history."""
    if previous_trace is not None:
        history: List[Dict[str, Any]] = list(previous_trace.unified_drift_history)
    else:
        history = []
    history.append(_build_classification_summary(classification))
    return history


def _build_confidence_evolution(
    confirmation: DriftConfirmationState,
    previous_trace: Optional[DriftTrace],
) -> List[float]:
    """Append the current accumulated confidence to the confidence evolution."""
    if previous_trace is not None:
        evolution: List[float] = list(previous_trace.drift_confidence_evolution)
    else:
        evolution = []
    evolution.append(confirmation.confidence)
    return evolution


def _build_recovery_decisions(
    decision: DriftRecoveryDecision,
    previous_trace: Optional[DriftTrace],
) -> List[Dict[str, Any]]:
    """Append the current recovery decision summary to the previous trace's history."""
    if previous_trace is not None:
        decisions: List[Dict[str, Any]] = list(
            previous_trace.drift_recovery_decisions
        )
    else:
        decisions = []
    decisions.append(_build_recovery_summary(decision))
    return decisions


# ── public API ───────────────────────────────────────────────────────────────


def build_drift_trace(
    unified_classification: UnifiedDriftClassification,
    confirmation_state: DriftConfirmationState,
    recovery_decision: DriftRecoveryDecision,
    previous_trace: Optional[DriftTrace] = None,
) -> DriftTrace:
    """
    Build a per‑segment unified drift trace from the drift pipeline outputs.

    Args:
        unified_classification:
            Unified drift classification from 2.9.2.
        confirmation_state:
            Drift confirmation state from 2.9.3.
        recovery_decision:
            Drift recovery decision from 2.9.4.
        previous_trace:
            Optional previous ``DriftTrace`` for appending to history.
            ``None`` on first cycle.

    Returns:
        A ``DriftTrace`` with pure, defensive‑copied data.
    """
    # ── unified drift history ──────────────────────────────────────────────
    drift_history = _build_unified_drift_history(
        unified_classification, previous_trace
    )

    # ── confidence evolution ───────────────────────────────────────────────
    confidence_evolution = _build_confidence_evolution(
        confirmation_state, previous_trace
    )

    # ── recovery decisions ─────────────────────────────────────────────────
    recovery_decisions = _build_recovery_decisions(
        recovery_decision, previous_trace
    )

    return DriftTrace(
        unified_drift_history=drift_history,
        drift_confidence_evolution=confidence_evolution,
        drift_recovery_decisions=recovery_decisions,
    )
