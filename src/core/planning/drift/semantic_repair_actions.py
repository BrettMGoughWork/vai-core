"""
Phase 2.8.4 — Semantic Repair Actions
=====================================

Produces a ``SemanticRepairPlan`` that describes how Stratum‑2 should
respond when semantic drift is detected across cycles.

The repair engine is **pure** and **deterministic**:

- Reads the ``SemanticDriftClassification`` produced by 2.8.3.
- Generates a structured repair plan (human‑readable action strings).
- Never mutates the classification or any other input.
- No LLM calls, no tool calls, no I/O.

Repair action mapping
---------------------
================================== ======================================
Category                            Repair Action
================================== ======================================
``contradictprior_behaviour``       ``rewrite step``
``contradictplan``                  ``rewrite plan``
``contradictsubgoal``               ``rewrite subgoal``
``contradictmemory``                ``rewrite segment``
================================== ======================================

Actions are emitted in deterministic order (sorted by category name).
"""
from __future__ import annotations

from typing import List

from src.core.planning.drift.semantic_signal_types import (
    _SEMANTIC_CATEGORY_REPAIR_ACTION,
    SemanticDriftClassification,
    SemanticRepairPlan,
)


def repair_semantic_drift(
    classification: SemanticDriftClassification,
) -> SemanticRepairPlan:
    """
    Generate a repair plan from a semantic drift classification.

    Args:
        classification:
            The classification produced by ``classify_semantic_drift()``.

    Returns:
        A ``SemanticRepairPlan`` with ``needs_repair``, sorted action
        strings, confidence, categories, and streak.
    """
    # ── no drift → no repair ──────────────────────────────────────────
    if classification.status == "no_drift":
        return SemanticRepairPlan(
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
        action = _SEMANTIC_CATEGORY_REPAIR_ACTION.get(category)
        if action is not None:
            actions.append(action)

    return SemanticRepairPlan(
        needs_repair=True,
        repair_actions=actions,
        confidence=classification.confidence,
        categories=list(classification.categories),  # defensive copy
        streak=classification.streak,
    )
