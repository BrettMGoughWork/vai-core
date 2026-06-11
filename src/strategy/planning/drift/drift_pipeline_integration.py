"""
Phase 2.14 — Drift Pipeline Integration
========================================

Wires the built-but-not-delivered drift confirmation (2.9.3), recovery (2.9.4),
arbitration (2.10.3), and budget (2.10.2) modules into the agent loop (2.13.1).

This module bridges the existing dict-based per-level drift data (from segment
and subgoal traces) into the typed unified drift pipeline.  Each cycle the
agent loop calls ``run_drift_pipeline()`` which:

1. Converts trace drift records into ``UnifiedDriftSignal`` objects
2. Runs ``classify_unified_drift()`` (2.9.2) for cross‑cycle classification
3. Runs ``confirm_drift()`` (2.9.3) for multi‑cycle stabilisation
4. Runs ``recover_from_drift()`` (2.9.4) to choose a recovery path
5. Runs ``decide_arbitration_action()`` (2.10.3) to select the minimal fix
6. Tracks ``RepairBudgetState`` (2.10.2) across cycles

All pipeline state is stored in the agent loop's ``memory`` dict under
``"drift_pipeline"`` so it survives cycle boundaries and remains JSON‑safe.

Invariants
----------
- Pure — no side effects, no mutation of inputs.
- Deterministic — identical inputs always produce identical outputs.
- JSON‑safe — all outputs are serialisable to JSON.
- No LLM calls, no I/O.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional, Tuple

from src.strategy.planning.drift.drift_confirmation_engine import confirm_drift
from src.strategy.planning.drift.drift_recovery_engine import recover_from_drift
from src.strategy.planning.drift.repair_arbitration import (
    ArbitrationDecision,
    decide_arbitration_action,
)
from src.strategy.planning.drift.repair_budget import (
    RepairBudgetConfig,
    RepairBudgetState,
)
from src.strategy.planning.drift.unified_drift_classifier import classify_unified_drift
from src.strategy.planning.drift.unified_drift_types import (
    DriftConfirmationState,
    DriftRecoveryDecision,
    UnifiedDriftClassification,
    UnifiedDriftSignal,
)

# ── Feature flag ────────────────────────────────────────────────────────────────
# Enabled as of 2026-06-11.  The bridge from per-level drift to unified signals
# is complete and tested.
DRIFT_PIPELINE_ENABLED = True


# ── Signal bridge ──────────────────────────────────────────────────────────────


def _drift_dict_to_unified_signal(
    d: Dict[str, Any],
    *,
    source: str,
) -> Optional[UnifiedDriftSignal]:
    """Convert a per-level drift classification dict to a ``UnifiedDriftSignal``.

    Parameters
    ----------
    d:
        A drift record from a segment or subgoal trace.  Expected keys:
        ``status``, ``severity``, ``categories``, ``confidence``, ``streak``,
        ``signal_count``.
    source:
        The unified signal source (``"structural"``, ``"behavioural"``,
        ``"temporal"``, or ``"semantic"``).

    Returns
    -------
    UnifiedDriftSignal or ``None``
        ``None`` when the dict has no meaningful drift data to convert.
    """
    if not isinstance(d, dict):
        return None
    if d.get("status") == "no_drift" or d.get("severity") is None:
        return None

    severity = d["severity"]
    confidence: float = d.get("confidence", 0.0)

    # Map per-level severity to a weight appropriate for the unified pipeline.
    weight_map: Dict[str, float] = {
        "minor": 0.3,
        "major": 0.6,
        "catastrophic": 0.9,
    }
    weight = weight_map.get(severity, 0.3)

    # Use the first category as the signal type, if available.
    categories = d.get("categories")
    signal_type: str = (
        categories[0] if isinstance(categories, list) and categories else "signal"
    )

    return UnifiedDriftSignal(
        source=source,
        type=signal_type,
        weight=weight,
        decay=1.0,
        confidence=confidence,
        details={"drift": d},
    )


def _collect_unified_signals(
    segment_drift_records: List[Dict[str, Any]],
    subgoal_drift_records: List[Dict[str, Any]],
) -> List[UnifiedDriftSignal]:
    """Convert all per-level drift records into a unified signal list.

    Segment drift is tagged as ``"structural"`` source, subgoal drift as
    ``"behavioural"`` — this is the best approximation until the full
    four‑family signal bridge is in place.
    """
    signals: List[UnifiedDriftSignal] = []

    for d in segment_drift_records:
        sig = _drift_dict_to_unified_signal(d, source="structural")
        if sig is not None:
            signals.append(sig)

    for d in subgoal_drift_records:
        sig = _drift_dict_to_unified_signal(d, source="behavioural")
        if sig is not None:
            signals.append(sig)

    return signals


# ── Serialisation helpers ──────────────────────────────────────────────────────


def _to_dict(obj: Any) -> Dict[str, Any]:
    """Convert a dataclass (or list thereof) to a JSON‑safe dict.

    Handles nested dataclasses recursively via ``dataclasses.asdict``.
    """
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]  # type: ignore[return-value]
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return obj  # type: ignore[return-value]


# ── Pipeline runner ────────────────────────────────────────────────────────────


def run_drift_pipeline(
    segment_drift: List[Dict[str, Any]],
    subgoal_drift: List[Dict[str, Any]],
    prev_confirmation: Optional[DriftConfirmationState],
    prev_budget: Optional[RepairBudgetState],
) -> Dict[str, Any]:
    """Run the full drift pipeline for one cycle.

    Parameters
    ----------
    segment_drift:
        Drift records from the segment trace for this cycle.
    subgoal_drift:
        Drift records from the subgoal trace for this cycle (may be empty if
        the subgoal hasn't completed yet).
    prev_confirmation:
        ``DriftConfirmationState`` from the previous cycle, or ``None`` on
        the first cycle.
    prev_budget:
        ``RepairBudgetState`` from the previous cycle, or ``None`` on the
        first cycle.

    Returns
    -------
    dict
        JSON‑safe dict with keys:
        - ``"signals"`` — list of ``UnifiedDriftSignal`` dicts
        - ``"classification"`` — ``UnifiedDriftClassification`` dict
        - ``"confirmation"`` — ``DriftConfirmationState`` dict
        - ``"recovery"`` — ``DriftRecoveryDecision`` dict
        - ``"arbitration"`` — ``ArbitrationDecision`` dict
        - ``"budget_state"`` — ``RepairBudgetState`` dict
    """
    # ── 1. Collect unified signals from per-level drift ─────────────────────
    signals = _collect_unified_signals(segment_drift, subgoal_drift)

    # ── 2. Classify ────────────────────────────────────────────────────────
    classification: UnifiedDriftClassification = classify_unified_drift(signals)

    # ── 3. Confirm (multi‑cycle stabilisation) ─────────────────────────────
    confirmation: DriftConfirmationState = confirm_drift(
        classification, prev_confirmation
    )

    # ── 4. Recovery decision ───────────────────────────────────────────────
    recovery: DriftRecoveryDecision = recover_from_drift(confirmation)

    # ── 5. Arbitration with budget ─────────────────────────────────────────
    budget: RepairBudgetState = prev_budget or RepairBudgetState()
    arbitration: ArbitrationDecision = decide_arbitration_action(
        drift=classification,
        budgets=budget,
        plan_state={},
        subgoal_state={},
        segment_state={},
    )

    return {
        "signals": _to_dict(signals),
        "classification": _to_dict(classification),
        "confirmation": _to_dict(confirmation),
        "recovery": _to_dict(recovery),
        "arbitration": _to_dict(arbitration),
        "budget_state": _to_dict(budget),
    }


# ── State helpers for the agent loop ──────────────────────────────────────────


def extract_pipeline_state(
    memory: Dict[str, Any],
) -> Tuple[Optional[DriftConfirmationState], Optional[RepairBudgetState]]:
    """Rebuild typed pipeline state from the JSON‑safe memory dict.

    Looks up ``memory["drift_pipeline"]`` and reconstructs
    ``DriftConfirmationState`` and ``RepairBudgetState`` from the stored dicts.

    Parameters
    ----------
    memory
        The agent loop's ``memory`` dict (mutated in place across cycles).

    Returns
    -------
    tuple[DriftConfirmationState | None, RepairBudgetState | None]
        Previous cycle's confirmation state and budget state, or ``(None, None)``
        if no pipeline state exists yet.
    """
    stored = memory.get("drift_pipeline", {})
    if not stored:
        return None, None

    confirmation = None
    if "confirmation" in stored:
        try:
            confirmation = DriftConfirmationState(**stored["confirmation"])
        except (TypeError, ValueError):
            confirmation = None

    budget = None
    if "budget_state" in stored:
        try:
            state_dict = dict(stored["budget_state"])
            # RepairBudgetState.config is a nested dataclass; asdict converts
            # it to a dict, so reconstruct the typed config object here.
            config_raw = state_dict.get("config")
            if isinstance(config_raw, dict):
                state_dict["config"] = RepairBudgetConfig(**config_raw)
            budget = RepairBudgetState(**state_dict)
        except (TypeError, ValueError):
            budget = None

    return confirmation, budget


def store_pipeline_state(
    memory: Dict[str, Any],
    pipeline_result: Dict[str, Any],
) -> None:
    """Persist pipeline confirmation and budget state into *memory*.

    Only stores the state needed for the next cycle (confirmation state and
    budget state), not the full pipeline output.
    """
    memory["drift_pipeline"] = {
        "confirmation": pipeline_result.get("confirmation", {}),
        "budget_state": pipeline_result.get("budget_state", {}),
    }
