"""
Phase 2.11.3 — Segment‑Level Drift
===================================

Deterministic, pure‑function drift handling at the segment level:
- drift classification per segment
- drift action decision (none / repair / replan)
- repair application
- SegmentDriftResult production

Constraints
-----------
- Pure functions only — no side effects, no mutation of inputs.
- No I/O, no inference, no LLM calls.
- Deterministic — identical inputs always produce identical outputs.
- JSON‑safe — all output structures are serialisable to JSON.
- Reuses the existing drift + repair substrate from 2.11.2 reflection and
  ``repair_action_library``.
- Replan is a placeholder (no Stratum‑1 integration yet).
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict

from src.strategy.planning.drift.repair_action_library import repair_segment
from src.strategy.types.plan_segment import PlanSegment

from .reflection import _segment_to_safe_dict as _safe_dict
from .reflection import evaluate_segment_drift as _classify_drift


# ──────────────────────────────────────────────────────────────────────────────
# SegmentDriftResult
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SegmentDriftResult:
    """Deterministic drift result for a single segment.

    Fields
    ------
    drift
        Dict snapshot from the drift classifier with ``status``, ``severity``,
        ``categories``, ``confidence``, ``streak``, and ``signal_count``.
    action
        Decided action — ``"none"``, ``"repair_segment"``, or ``"replan_segment"``.
    repaired_segment
        The repaired segment as a JSON‑safe dict, or the original segment dict
        if no repair was performed.
    requires_replan
        ``True`` when drift severity exceeds the repair threshold
        (i.e. action is ``"replan_segment"``).
    """

    drift: Dict[str, Any]
    action: str
    repaired_segment: Dict[str, Any]
    requires_replan: bool

    def __hash__(self) -> int:
        """Deterministic hash via JSON‑stable serialisation of dict fields."""
        return hash(
            (
                json.dumps(self.drift, sort_keys=True),
                self.action,
                json.dumps(self.repaired_segment, sort_keys=True),
                self.requires_replan,
            )
        )


# ──────────────────────────────────────────────────────────────────────────────
# Pure functions
# ──────────────────────────────────────────────────────────────────────────────


def classify_segment_drift(segment: PlanSegment) -> dict:
    """Classify drift at the segment level.

    Reuses the existing drift classifier from the reflection module (2.11.2).
    No new drift categories are introduced.

    Returns
    -------
    dict
        Keys: ``status``, ``severity``, ``categories``, ``confidence``,
        ``streak``, ``signal_count``.
    """
    return _classify_drift(segment)


def decide_segment_drift_action(drift: dict) -> str:
    """Decide what action to take based on drift classification.

    Rules
    -----
    - No drift → ``"none"``
    - Drift severity < catastrophic → ``"repair_segment"``
    - Drift severity == catastrophic → ``"replan_segment"``

    Returns
    -------
    str
        One of ``"none"``, ``"repair_segment"``, or ``"replan_segment"``.
    """
    if drift.get("status") == "no_drift":
        return "none"
    if drift.get("severity") == "catastrophic":
        return "replan_segment"
    return "repair_segment"


def apply_segment_repair(segment: PlanSegment, drift: dict) -> Dict[str, Any]:
    """Apply segment‑level repair if drift is detected.

    Reuses ``repair_segment`` from the existing repair action library.
    Returns the original segment as a safe dict when no drift is present.

    Returns
    -------
    dict
        JSON‑safe dict representation of the (possibly repaired) segment.
    """
    if drift.get("status") == "no_drift":
        return _safe_dict(segment)
    repaired = repair_segment(segment)
    return _safe_dict(repaired)


def evaluate_segment_drift(segment: PlanSegment) -> SegmentDriftResult:
    """Produce a complete segment‑level drift result.

    Runs the pipeline in deterministic order:
    1. classify drift
    2. decide action
    3. apply repair (if needed)
    4. produce SegmentDriftResult

    Rules
    -----
    - ``"none"`` → return original segment, ``requires_replan=False``.
    - ``"repair_segment"`` → return repaired segment, ``requires_replan=False``.
    - ``"replan_segment"`` → return original segment, ``requires_replan=True``
      (replan is a placeholder — no S1 integration yet).

    Returns
    -------
    SegmentDriftResult
        Complete drift evaluation result.
    """
    drift = classify_segment_drift(segment)
    action = decide_segment_drift_action(drift)

    if action == "none":
        repaired = _safe_dict(segment)
    elif action == "repair_segment":
        repaired = apply_segment_repair(segment, drift)
    else:  # "replan_segment" — placeholder, return original
        repaired = _safe_dict(segment)

    return SegmentDriftResult(
        drift=drift,
        action=action,
        repaired_segment=repaired,
        requires_replan=action == "replan_segment",
    )
