"""
Phase 2.9.4 — Drift Recovery Engine
====================================

Implements ``recover_from_drift()``, a pure, deterministic function that
converts a confirmed drift state into a recovery decision:

- **no drift** → action ``"none"``
- **minor** → ``"repair"``
- **major** → ``"replan"``
- **catastrophic** → escalate to regeneration based on confidence thresholds,
  or ``"full_reset"`` when the streak reaches 3 cycles.

Invariants
----------
- Pure — no side effects, no mutation of inputs.
- Deterministic — identical inputs always produce identical outputs.
- JSON‑safe — all outputs are serialisable to JSON.
- No LLM calls, no imports outside stdlib.
"""
from __future__ import annotations

from typing import List

from src.core.planning.drift.unified_drift_types import (
    DriftConfirmationState,
    DriftRecoveryDecision,
)

# ── Catastrophic regeneration thresholds ─────────────────────────────────────
_CATASTROPHIC_REGEN_SEGMENT: float = 0.85
_CATASTROPHIC_REGEN_PLAN: float = 0.95
_FULL_RESET_STREAK: int = 3


def _build_reasons(
    severity: str,
    confidence: float,
    streak: int,
    hysteresis: float,
    action: str,
) -> List[str]:
    """Build deterministic, JSON‑safe reason strings."""
    return [
        f"severity={severity}",
        f"confidence={confidence:.4f}",
        f"streak={streak}",
        f"hysteresis={hysteresis:.4f}",
        f"action={action}",
    ]


def _choose_catastrophic_action(
    confidence: float,
    streak: int,
) -> str:
    """Choose the appropriate regeneration action for catastrophic drift."""
    if streak >= _FULL_RESET_STREAK:
        return "full_reset"
    if confidence < _CATASTROPHIC_REGEN_SEGMENT:
        return "regen_segment"
    if confidence < _CATASTROPHIC_REGEN_PLAN:
        return "regen_plan"
    return "regen_subgoal"


def recover_from_drift(
    confirmation: DriftConfirmationState,
) -> DriftRecoveryDecision:
    """
    Produce a deterministic recovery decision from confirmed drift.

    Parameters
    ----------
    confirmation:
        The current cycle's drift confirmation state from
        ``confirm_drift()``.

    Returns
    -------
    DriftRecoveryDecision
        A frozen, JSON‑safe decision prescribing the recovery path.
    """
    # ── 1. No drift ────────────────────────────────────────────────────────
    if not confirmation.confirmed:
        reasons = _build_reasons(
            severity="minor",
            confidence=confirmation.confidence,
            streak=confirmation.streak,
            hysteresis=confirmation.hysteresis,
            action="none",
        )
        return DriftRecoveryDecision(
            action="none",
            severity="minor",
            confidence=confirmation.confidence,
            streak=confirmation.streak,
            hysteresis=confirmation.hysteresis,
            reasons=reasons,
        )

    # ── 2. Drift detected → choose recovery path ───────────────────────────
    severity = confirmation.severity

    if severity == "minor":
        action = "repair"
    elif severity == "major":
        action = "replan"
    else:  # catastrophic
        action = _choose_catastrophic_action(
            confirmation.confidence,
            confirmation.streak,
        )

    reasons = _build_reasons(
        severity=severity,
        confidence=confirmation.confidence,
        streak=confirmation.streak,
        hysteresis=confirmation.hysteresis,
        action=action,
    )

    return DriftRecoveryDecision(
        action=action,
        severity=severity,
        confidence=confirmation.confidence,
        streak=confirmation.streak,
        hysteresis=confirmation.hysteresis,
        reasons=reasons,
    )
