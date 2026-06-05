"""
Phase 2.12.3 — Subgoal‑Level Drift
===================================

Deterministic, pure‑function drift handling at the subgoal level:
- drift classification per subgoal
- drift action decision (none / repair / replan)
- repair application
- SubgoalDriftResult production

Constraints
-----------
- Pure functions only — no side effects, no mutation of inputs.
- No I/O, no inference, no LLM calls.
- Deterministic — identical inputs always produce identical outputs.
- JSON‑safe — all output structures are serialisable to JSON.
- Reuses the existing drift + repair substrate from 2.12.2 reflection and
  ``repair_action_library``.
- Replan is a placeholder (no Stratum‑1 integration yet).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from dataclasses import dataclass

from src.core.planning.drift.repair_action_library import repair_subgoal
from src.core.types.subgoal import Subgoal

from .reflection import _subgoal_to_safe_dict as _safe_dict
from .reflection import evaluate_subgoal_drift as _classify_drift


# ──────────────────────────────────────────────────────────────────────────────
# SubgoalDriftResult
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SubgoalDriftResult:
    """Deterministic drift result for a single subgoal.

    Fields
    ------
    drift
        Dict snapshot from the drift classifier with ``status``, ``severity``,
        ``categories``, ``confidence``, ``streak``, and ``signal_count``.
    action
        Decided action — ``"none"``, ``"repair_subgoal"``, or ``"replan_subgoal"``.
    repaired_subgoal
        The repaired subgoal as a JSON‑safe dict, or the original subgoal dict
        if no repair was performed.
    requires_replan
        ``True`` when drift severity exceeds the repair threshold
        (i.e. action is ``"replan_subgoal"``).
    """

    drift: Dict[str, Any]
    action: str
    repaired_subgoal: Dict[str, Any]
    requires_replan: bool

    def __hash__(self) -> int:
        """Deterministic hash via JSON‑stable serialisation of dict fields."""
        return hash(
            (
                json.dumps(self.drift, sort_keys=True),
                self.action,
                json.dumps(self.repaired_subgoal, sort_keys=True),
                self.requires_replan,
            )
        )


# ──────────────────────────────────────────────────────────────────────────────
# Pure functions
# ──────────────────────────────────────────────────────────────────────────────


def classify_subgoal_drift(
    subgoal: Subgoal,
    segments: Optional[List[Any]] = None,
) -> dict:
    """Classify drift at the subgoal level.

    Reuses the existing drift classifier from the reflection module (2.12.2).
    No new drift categories are introduced.

    Returns
    -------
    dict
        Keys: ``status``, ``severity``, ``categories``, ``confidence``,
        ``streak``, ``signal_count``.
    """
    return _classify_drift(subgoal, segments)


def decide_subgoal_drift_action(drift: dict) -> str:
    """Decide what action to take based on drift classification.

    Rules
    -----
    - No drift → ``"none"``
    - Drift severity < catastrophic → ``"repair_subgoal"``
    - Drift severity == catastrophic → ``"replan_subgoal"``

    Returns
    -------
    str
        One of ``"none"``, ``"repair_subgoal"``, or ``"replan_subgoal"``.
    """
    if drift.get("status") == "no_drift":
        return "none"
    if drift.get("severity") == "catastrophic":
        return "replan_subgoal"
    return "repair_subgoal"


def apply_subgoal_repair(subgoal: Subgoal, drift: dict) -> Dict[str, Any]:
    """Apply subgoal‑level repair if drift is detected.

    Reuses ``repair_subgoal`` from the existing repair action library.
    Returns the original subgoal as a safe dict when no drift is present.

    Returns
    -------
    dict
        JSON‑safe dict representation of the (possibly repaired) subgoal.
    """
    if drift.get("status") == "no_drift":
        return _safe_dict(subgoal)
    repaired = repair_subgoal(subgoal)
    return _safe_dict(repaired)


def evaluate_subgoal_drift(
    subgoal: Subgoal,
    segments: Optional[List[Any]] = None,
) -> SubgoalDriftResult:
    """Produce a complete subgoal‑level drift result.

    Runs the pipeline in deterministic order:
    1. classify drift
    2. decide action
    3. apply repair (if needed)
    4. produce SubgoalDriftResult

    Rules
    -----
    - ``"none"`` → return original subgoal, ``requires_replan=False``.
    - ``"repair_subgoal"`` → return repaired subgoal, ``requires_replan=False``.
    - ``"replan_subgoal"`` → return original subgoal, ``requires_replan=True``
      (replan is a placeholder — no S1 integration yet).

    Returns
    -------
    SubgoalDriftResult
        Complete drift evaluation result.
    """
    drift = classify_subgoal_drift(subgoal, segments)
    action = decide_subgoal_drift_action(drift)

    if action == "none":
        repaired = _safe_dict(subgoal)
    elif action == "repair_subgoal":
        repaired = apply_subgoal_repair(subgoal, drift)
    else:  # "replan_subgoal" — placeholder, return original
        repaired = _safe_dict(subgoal)

    return SubgoalDriftResult(
        drift=drift,
        action=action,
        repaired_subgoal=repaired,
        requires_replan=action == "replan_subgoal",
    )
