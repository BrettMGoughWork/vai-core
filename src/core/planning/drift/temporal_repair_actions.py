"""
Phase 2.7.4 — Temporal Repair Actions
=====================================

Produces a ``TemporalRepairPlan`` that describes how Stratum‑2 should
respond to multi‑cycle temporal drift detected across cycles.

The repair engine is **pure** and **deterministic**:

- Reads the ``TemporalDriftClassification`` produced by 2.7.3.
- Generates a structured repair plan (human‑readable action strings).
- Never mutates the classification or any other input.
- No LLM calls, no tool calls, no I/O.

Repair action mapping
---------------------
================================= ======================================
Category                          Repair Action
================================= ======================================
``stall``                         ``regenerate segment``
``repetition``                    ``reset segment state``
``oscillation``                   ``re‑decompose subgoal``
``regression``                    ``regenerate plan``
================================= ======================================

Actions are emitted in deterministic order (sorted by category name).
"""
from __future__ import annotations

from typing import List

from src.core.planning.drift.temporal_signal_types import (
    _CATEGORY_REPAIR_ACTION,
    TemporalDriftClassification,
    TemporalRepairPlan,
)


def repair_temporal_drift(
    classification: TemporalDriftClassification,
) -> TemporalRepairPlan:
    """
    Generate a repair plan from a temporal drift classification.

    Args:
        classification:
            The classification produced by ``classify_temporal_drift()``.

    Returns:
        A ``TemporalRepairPlan`` with ``needs_repair``, sorted action
        strings, confidence, categories, and streak.
    """
    # ── no drift → no repair ──────────────────────────────────────────
    if classification.status == "no_drift":
        return TemporalRepairPlan(
            needs_repair=False,
            repair_actions=[],
            confidence=classification.confidence,
            categories=list(classification.categories),
            streak=classification.streak,
        )

    # ── derive actions from categories ─────────────────────────────────
    # Categories already deduplicated and sorted by the classifier.
    # Map each to its repair action in deterministic order.
    actions: List[str] = []
    for category in classification.categories:
        action = _CATEGORY_REPAIR_ACTION.get(category)
        if action is not None:
            actions.append(action)

    return TemporalRepairPlan(
        needs_repair=True,
        repair_actions=actions,
        confidence=classification.confidence,
        categories=list(classification.categories),  # defensive copy
        streak=classification.streak,
    )
