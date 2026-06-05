"""
Phase 2.10.3 — Repair Arbitration Engine
=========================================

Decides the correct action when drift or structural issues are detected,
choosing between repair, replan, regenerate segment, regenerate subgoal,
and catastrophic escalation.

Arbitration is:
* deterministic — no randomness, no LLM calls, no external state
* pure — never mutates inputs, always returns a new frozen decision
* JSON‑safe — all output is serialisable
* minimal — chooses the least invasive action that resolves the drift

Decision inputs
---------------
- ``UnifiedDriftClassification`` — drift severity, categories, confidence
- ``RepairBudgetState`` — per‑scope budget tracking
- ``PlanState`` — plan state (accepted but not deeply inspected in 2.10.3)
- ``SubgoalState`` — subgoal state (accepted but not deeply inspected)
- ``SegmentState`` — segment state (accepted but not deeply inspected)

Decision output
---------------
``ArbitrationDecision`` — frozen dataclass with action, reason, metadata.

Decision tree
-------------
1. Catastrophic drift → "catastrophic" immediately
2. Budget exhaustion → escalate to replan / regen_* based on scope
3. Drift category + severity → determine base action
4. Confidence tier → adjust (low → repair, medium → unchanged, high → escalate)
5. Minimality check → choose least invasive valid action
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Literal

from src.core.planning.drift.unified_drift_types import UnifiedDriftClassification
from src.core.planning.drift.repair_budget import RepairBudgetState, is_budget_exhausted

# Re-use the budget scope literal
Scope = Literal["cycle", "subgoal", "plan", "global"]

# ── ArbitrationDecision ──────────────────────────────────────────────────────────

_VALID_ARBITRATION_ACTIONS = frozenset({
    "none",
    "repair",
    "replan",
    "regen_segment",
    "regen_subgoal",
    "catastrophic",
})

_ACTION_SEVERITY: Dict[str, int] = {
    "repair": 0,
    "replan": 1,
    "regen_segment": 2,
    "regen_subgoal": 3,
    "catastrophic": 4,
}


@dataclass(frozen=True)
class ArbitrationDecision:
    """Deterministic arbitration decision for a single drift cycle.

    Pure, frozen, JSON‑safe — never mutated after construction.

    ``action``
        One of ``"repair"``, ``"replan"``, ``"regen_segment"``,
        ``"regen_subgoal"``, or ``"catastrophic"``.
    ``reason``
        Deterministic human‑readable explanation of why this action was chosen.
    ``metadata``
        JSON‑safe dict with diagnostic information (severity, categories,
        confidence tier, budget state).  Defensively copied at construction.
    """
    action: Literal["repair", "replan", "regen_segment", "regen_subgoal", "catastrophic"]
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action not in _VALID_ARBITRATION_ACTIONS:
            raise ValueError(
                f"action must be one of {sorted(_VALID_ARBITRATION_ACTIONS)}, "
                f"got {self.action!r}"
            )
        if not isinstance(self.reason, str):
            raise ValueError(
                f"reason must be a string, got {type(self.reason).__name__}"
            )
        # Defensive copy of metadata
        meta_copy = copy.deepcopy(self.metadata)
        object.__setattr__(self, "metadata", meta_copy)


# ── Internal helpers ─────────────────────────────────────────────────────────────

def _invasiveness(action: str) -> int:
    """Return numeric invasiveness for comparison (lower = less invasive)."""
    return _ACTION_SEVERITY.get(action, 99)


def _dominant_category(classification: UnifiedDriftClassification) -> Optional[str]:
    """Return the source with the highest‑weight signal, or None if empty."""
    if not classification.reasons:
        return None
    best = max(classification.reasons, key=lambda s: s.weight)
    return best.source


def _confidence_tier(confidence: float) -> str:
    """Map a confidence value to low / medium / high."""
    if confidence < 0.4:
        return "low"
    if confidence < 0.7:
        return "medium"
    return "high"


def _base_action(
    classification: UnifiedDriftClassification,
) -> str:
    """Determine the base (pre‑confidence‑adjusted) action from category and severity."""
    severity = classification.severity
    dominant = _dominant_category(classification)

    # Catastrophic is handled by the caller before this function.
    if severity == "catastrophic":
        return "catastrophic"

    # ── Category‑first rules ──
    if dominant == "structural":
        if severity == "major":
            return "regen_segment"  # structural + major → escalate
        return "repair"

    if dominant == "behavioural":
        return "regen_segment"

    if dominant == "temporal":
        return "regen_segment"

    if dominant == "semantic":
        if severity == "major":
            return "regen_segment"  # semantic + severity >= major → escalate
        return "repair"

    # ── Default fallback (no dominant category) ──
    if severity == "major":
        return "regen_segment"
    return "repair"


_ESCALATION_MAP: Dict[str, str] = {
    "repair": "replan",
    "replan": "regen_segment",
    "regen_segment": "regen_subgoal",
    "regen_subgoal": "catastrophic",
    "catastrophic": "catastrophic",  # ceiling
}

_DOWNGRADE_MAP: Dict[str, str] = {
    "repair": "repair",  # floor
    "replan": "repair",
    "regen_segment": "repair",
    "regen_subgoal": "repair",
    "catastrophic": "repair",
}


def _apply_confidence(action: str, confidence: float) -> str:
    """Adjust *action* based on confidence tier.

    - low  → force "repair" (downgrade)
    - med  → no change
    - high → escalate one level
    """
    tier = _confidence_tier(confidence)
    if tier == "low":
        return _DOWNGRADE_MAP.get(action, "repair")
    if tier == "high":
        return _ESCALATION_MAP.get(action, action)
    return action  # medium — no change


def _check_budget_exhaustion(
    budgets: RepairBudgetState,
) -> Optional[str]:
    """Return the escalated action if any budget scope is exhausted, else None.

    Checks in order of escalating invasiveness.
    """
    if is_budget_exhausted(budgets, "global"):
        return "replan"
    if is_budget_exhausted(budgets, "plan"):
        return "replan"
    if is_budget_exhausted(budgets, "subgoal"):
        return "regen_subgoal"
    if is_budget_exhausted(budgets, "cycle"):
        return "regen_segment"
    return None


def _minimality(candidate: str, fallback: str) -> str:
    """Return the less invasive of *candidate* and *fallback*."""
    return candidate if _invasiveness(candidate) <= _invasiveness(fallback) else fallback


def _build_metadata(
    classification: UnifiedDriftClassification,
    budgets: RepairBudgetState,
    tier: str,
    dominant: Optional[str],
    budget_trigger: Optional[str],
) -> Dict[str, Any]:
    """Build a JSON‑safe metadata dict for the arbitration decision."""
    return {
        "severity": classification.severity,
        "categories": list(classification.categories),
        "confidence": classification.confidence,
        "confidence_tier": tier,
        "dominant_category": dominant,
        "budget_exhausted": {
            "cycle": is_budget_exhausted(budgets, "cycle"),
            "subgoal": is_budget_exhausted(budgets, "subgoal"),
            "plan": is_budget_exhausted(budgets, "plan"),
            "global": is_budget_exhausted(budgets, "global"),
        },
        "budget_trigger": budget_trigger,
        "usage": {
            "cycle": budgets.usage_cycle,
            "subgoal": budgets.usage_subgoal,
            "plan": budgets.usage_plan,
            "global": budgets.usage_global,
        },
    }


# ── Public API ───────────────────────────────────────────────────────────────────


def decide_arbitration_action(
    drift: UnifiedDriftClassification,
    budgets: RepairBudgetState,
    plan_state: object,
    subgoal_state: object,
    segment_state: object,
) -> ArbitrationDecision:
    """Determine the correct arbitration action for a drift cycle.

    Pure, deterministic — never mutates any input.

    Parameters
    ----------
    drift
        The unified drift classification produced by the classifier (2.9.2).
    budgets
        Current repair budget state (2.10.2).  Budget exhaustion can override
        the severity‑based action.
    plan_state
        Plan state snapshot.  Not deeply inspected in 2.10.3 — accepted as
        placeholder for future phases.
    subgoal_state
        Subgoal state snapshot.  Not deeply inspected.
    segment_state
        Segment state snapshot.  Not deeply inspected.

    Returns
    -------
    ArbitrationDecision
        Frozen decision with action, reason, and diagnostic metadata.
    """
    severity = drift.severity
    dominant = _dominant_category(drift)
    tier = _confidence_tier(drift.confidence)

    # ── 0. No drift → no action needed ──
    if drift.status == "no_drift":
        return ArbitrationDecision(
            action="none",
            reason="No drift detected — no action required.",
            metadata=_build_metadata(drift, budgets, tier, dominant, None),
        )

    # ── 1. Catastrophic drift → immediate escalation ──
    if severity == "catastrophic":
        return ArbitrationDecision(
            action="catastrophic",
            reason=(
                "Catastrophic drift severity — escalation to catastrophic "
                "recovery regardless of budgets or confidence."
            ),
            metadata=_build_metadata(drift, budgets, tier, dominant, None),
        )

    # ── 2. Budget exhaustion ──
    budget_action = _check_budget_exhaustion(budgets)
    if budget_action is not None:
        # Determine which scope triggered exhaustion
        if is_budget_exhausted(budgets, "global"):
            trigger_scope = "global"
        elif is_budget_exhausted(budgets, "plan"):
            trigger_scope = "plan"
        elif is_budget_exhausted(budgets, "subgoal"):
            trigger_scope = "subgoal"
        else:
            trigger_scope = "cycle"

        return ArbitrationDecision(
            action=budget_action,
            reason=(
                f"Budget exhausted for scope '{trigger_scope}' — "
                f"escalating to '{budget_action}'."
            ),
            metadata=_build_metadata(
                drift, budgets, tier, dominant, trigger_scope
            ),
        )

    # ── 3. Category + severity → base action ──
    base = _base_action(drift)

    # ── 4. Minimality: prefer repair when drift is minor and category suggests repair ──
    adjusted = base
    if drift.severity == "minor" and dominant in (None, "structural", "semantic"):
        adjusted = _minimality(adjusted, "repair")

    # ── 5. Confidence adjustment (applied AFTER minimality so high confidence
    #       can escalate past the minimality floor) ──
    adjusted = _apply_confidence(adjusted, drift.confidence)

    return ArbitrationDecision(
        action=adjusted,
        reason=(
            f"Severity={severity}, category={dominant}, "
            f"confidence={drift.confidence:.2f} ({tier}) → '{adjusted}'"
            + (f" (base was '{base}')" if adjusted != base else "")
        ),
        metadata=_build_metadata(drift, budgets, tier, dominant, None),
    )


# ── Individual choose_* helpers ──────────────────────────────────────────────────
# Each returns a specific action — useful as building blocks for the caller.


def choose_repair(
    drift: UnifiedDriftClassification,
    budgets: RepairBudgetState,
) -> ArbitrationDecision:
    """Return a 'repair' decision with deterministic reason."""
    return ArbitrationDecision(
        action="repair",
        reason=f"Repair selected for {drift.severity} drift "
               f"(categories: {sorted(drift.categories)})",
        metadata={"severity": drift.severity, "categories": list(drift.categories)},
    )


def choose_replan(
    drift: UnifiedDriftClassification,
    budgets: RepairBudgetState,
) -> ArbitrationDecision:
    """Return a 'replan' decision with deterministic reason."""
    return ArbitrationDecision(
        action="replan",
        reason=f"Replan required due to budget exhaustion "
               f"(global: {is_budget_exhausted(budgets, 'global')}, "
               f"plan: {is_budget_exhausted(budgets, 'plan')})",
        metadata={"severity": drift.severity, "categories": list(drift.categories)},
    )


def choose_regen_segment(
    drift: UnifiedDriftClassification,
    budgets: RepairBudgetState,
) -> ArbitrationDecision:
    """Return a 'regen_segment' decision with deterministic reason."""
    return ArbitrationDecision(
        action="regen_segment",
        reason=f"Segment regeneration selected for {drift.severity} drift",
        metadata={"severity": drift.severity, "categories": list(drift.categories)},
    )


def choose_regen_subgoal(
    drift: UnifiedDriftClassification,
    budgets: RepairBudgetState,
) -> ArbitrationDecision:
    """Return a 'regen_subgoal' decision with deterministic reason."""
    return ArbitrationDecision(
        action="regen_subgoal",
        reason=f"Subgoal regeneration selected for {drift.severity} drift "
               f"(budget exhausted: subgoal={is_budget_exhausted(budgets, 'subgoal')})",
        metadata={"severity": drift.severity, "categories": list(drift.categories)},
    )


def choose_catastrophic(
    drift: UnifiedDriftClassification,
    budgets: RepairBudgetState,
) -> ArbitrationDecision:
    """Return a 'catastrophic' decision with deterministic reason."""
    return ArbitrationDecision(
        action="catastrophic",
        reason=f"Catastrophic escalation triggered for severity={drift.severity}, "
               f"confidence={drift.confidence:.2f}",
        metadata={"severity": drift.severity, "categories": list(drift.categories)},
    )
