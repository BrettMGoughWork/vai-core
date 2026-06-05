"""
Phase 2.8.5 — Semantic Trace Builder
====================================

Constructs a ``SemanticTrace`` from semantic mismatches (2.8.1),
semantic drift signals (2.8.2), classification (2.8.3), repair plan (2.8.4),
and an optional previous trace for drift history.

The trace is **pure**, **deterministic**, and never mutates its inputs.

Trace Components
----------------
semantic_mismatches
    JSON‑safe list of mismatch summary dicts.  Each dict contains the
    mismatch ``type``, ``confidence``, and ``details``.  Sorted
    deterministically by ``type``.

semantic_repair_actions
    Defensive copy of ``SemanticRepairPlan.repair_actions`` sorted
    deterministically.

semantic_drift_history
    Appends the current ``SemanticDriftClassification`` (as a JSON‑safe
    summary dict with ``status``, ``categories``, ``confidence``,
    ``streak``) to the previous trace's history.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from src.core.planning.drift.segment_trace_types import SemanticTrace
from src.core.planning.drift.semantic_signal_types import (
    SemanticDriftClassification,
    SemanticDriftSignal,
    SemanticMismatch,
    SemanticRepairPlan,
)


# ── mismatch summaries ──────────────────────────────────────────────────────


def _build_mismatch_summaries(
    mismatches: List[SemanticMismatch],
) -> List[Dict[str, Any]]:
    """
    Convert ``SemanticMismatch`` objects into sorted JSON‑safe summary dicts.

    Each summary dict has keys ``type``, ``confidence``, and ``details``.
    Sorted deterministically by ``type``.
    """
    summaries: List[Dict[str, Any]] = []
    for m in mismatches:
        summaries.append({
            "type": m.type,
            "confidence": m.confidence,
            "details": copy.deepcopy(m.details),
        })
    # Deterministic ordering by type
    summaries.sort(key=lambda s: s["type"])
    return summaries


# ── classification history ──────────────────────────────────────────────────


def _build_classification_summary(
    classification: SemanticDriftClassification,
) -> Dict[str, Any]:
    """
    Convert a ``SemanticDriftClassification`` into a JSON‑safe summary dict.

    Keys: ``status``, ``categories``, ``confidence``, ``streak``.
    """
    return {
        "status": classification.status,
        "categories": list(classification.categories),
        "confidence": classification.confidence,
        "streak": classification.streak,
    }


def _build_drift_history(
    classification: SemanticDriftClassification,
    previous_trace: Optional[SemanticTrace],
) -> List[Dict[str, Any]]:
    """
    Build the semantic drift history list by appending the current
    classification summary to the previous trace's history.

    Returns a fresh list (defensive copy).
    """
    if previous_trace is not None:
        history: List[Dict[str, Any]] = list(previous_trace.semantic_drift_history)
    else:
        history = []

    history.append(_build_classification_summary(classification))
    return history


# ── public API ───────────────────────────────────────────────────────────────


def build_semantic_trace(
    mismatches: List[SemanticMismatch],
    drift_signals: List[SemanticDriftSignal],
    classification: SemanticDriftClassification,
    repair_plan: SemanticRepairPlan,
    previous_trace: Optional[SemanticTrace] = None,
) -> SemanticTrace:
    """
    Build a per‑segment semantic trace from semantic‑reasoning outputs.

    Args:
        mismatches:
            Semantic mismatches from 2.8.1.
        drift_signals:
            Semantic drift signals from 2.8.2 (accepted but not directly
            used in trace construction — the classification already
            captures the signal context).
        classification:
            Semantic drift classification from 2.8.3.
        repair_plan:
            Semantic repair plan from 2.8.4.
        previous_trace:
            Optional previous ``SemanticTrace`` for appending to drift
            history.  ``None`` on first cycle.

    Returns:
        A ``SemanticTrace`` with pure, defensive‑copied data.
    """
    # ── semantic mismatches ───────────────────────────────────────────────
    mismatch_summaries = _build_mismatch_summaries(mismatches)

    # ── semantic repair actions ───────────────────────────────────────────
    actions = sorted(repair_plan.repair_actions)

    # ── semantic drift history ────────────────────────────────────────────
    drift_history = _build_drift_history(classification, previous_trace)

    return SemanticTrace(
        semantic_mismatches=mismatch_summaries,
        semantic_repair_actions=actions,
        semantic_drift_history=drift_history,
    )
