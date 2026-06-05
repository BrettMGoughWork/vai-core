"""
Phase 2.9 — Unified Drift Signal Types
======================================

Phase 2.9.1 — ``UnifiedDriftSignal``
    A single, weighted, decaying drift signal that merges the four
    independent drift‑signal families (structural, behavioural, temporal,
    semantic) into one representation.

Phase 2.9.2 — ``UnifiedDriftClassification``
    A deterministic classification produced from a list of unified drift
    signals, with severity levels and multi‑cycle streak tracking.

Phase 2.9.3 — ``DriftConfirmationState``
    A frozen, JSON‑safe state produced by the drift confirmation engine,
    with multi‑cycle confirmation, confidence accumulation, hysteresis,
    and history tracking.

Phase 2.9.4 — ``DriftRecoveryDecision``
    A frozen, JSON‑safe decision produced by the drift recovery engine,
    choosing between repair, replan, regeneration, and full reset based
    on confirmed drift severity, confidence, and streak.

All dataclasses are frozen, JSON‑safe, and pure.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Literal

from src.core.types.json_pure import ensure_json_pure

# ── 2.9.1 — UnifiedDriftSignal ────────────────────────────────────────────────

_SOURCE_WEIGHTS: Dict[str, float] = {
    "structural": 1.0,
    "behavioural": 0.9,
    "temporal": 0.8,
    "semantic": 0.7,
}


@dataclass(frozen=True)
class UnifiedDriftSignal:
    """
    A unified, weighted drift signal produced by merging the four independent
    drift‑signal families.

    Pure, deterministic, JSON‑safe — never mutates inputs.

    ``source``
        Which signal family this originated from:
        ``"structural"``, ``"behavioural"``, ``"temporal"``, or ``"semantic"``.
    ``type``
        Signal subtype (e.g. ``"shape_mismatch"``, ``"oscillation"``,
        ``"contradict_plan"``).
    ``weight``
        ``confidence × source_weight``, clamped to [0.0, 1.0].
    ``decay``
        Decay factor in [0.0, 1.0].  Starts at 1.0 and decays by 0.1 each
        cycle when a matching signal (same source + type) was present in the
        previous unified list.
    ``confidence``
        Original confidence from the source signal, in [0.0, 1.0].
    ``details``
        JSON‑safe dict with contextual information from the source signal.
        Deep‑copied at construction to prevent external mutation.
    """

    source: Literal["structural", "behavioural", "temporal", "semantic"]
    type: str
    weight: float
    decay: float
    confidence: float
    details: Dict[str, Any]

    def __post_init__(self) -> None:
        if self.source not in _SOURCE_WEIGHTS:
            raise ValueError(
                f"source must be one of {sorted(_SOURCE_WEIGHTS)}, "
                f"got {self.source!r}"
            )
        if self.weight < 0.0 or self.weight > 1.0:
            raise ValueError(
                f"weight must be in [0.0, 1.0], got {self.weight}"
            )
        if self.decay < 0.0 or self.decay > 1.0:
            raise ValueError(
                f"decay must be in [0.0, 1.0], got {self.decay}"
            )
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        details_copy = copy.deepcopy(self.details)
        ensure_json_pure(details_copy)
        object.__setattr__(self, "details", details_copy)


# ── 2.9.2 — UnifiedDriftClassification ────────────────────────────────────────

_VALID_UNIFIED_STATUSES = frozenset({"no_drift", "drift_detected"})
_VALID_UNIFIED_SEVERITIES = frozenset({"minor", "major", "catastrophic"})


@dataclass(frozen=True)
class UnifiedDriftClassification:
    """
    Phase 2.9.2 — Deterministic classification of unified drift across cycles.

    Maps a list of ``UnifiedDriftSignal``\\ s into a single classification
    with severity, confidence, and multi‑cycle streak tracking.

    Pure, deterministic, JSON‑safe — never mutates inputs.

    ``status``
        ``"no_drift"`` when signals is empty, ``"drift_detected"`` otherwise.
    ``severity``
        One of ``"minor"`` (max weight < 0.4), ``"major"`` (0.4–0.75),
        or ``"catastrophic"`` (≥ 0.75).
    ``categories``
        Sorted list of unique ``UnifiedDriftSignal.type`` strings.
    ``confidence``
        ``min(1.0, base × decay_avg + 0.1 × streak)`` where base is the
        max signal weight and decay_avg is the mean signal decay.
    ``reasons``
        Defensive copy of the ``UnifiedDriftSignal``\\ s that triggered the
        classification.
    ``streak``
        Multi‑cycle confirmation counter.  Increments when the status matches
        the previous classification; resets to 1 otherwise.
    """

    status: Literal["no_drift", "drift_detected"]
    severity: Literal["minor", "major", "catastrophic"]
    categories: List[str]
    confidence: float
    reasons: List[UnifiedDriftSignal]
    streak: int

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        if self.status not in _VALID_UNIFIED_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_VALID_UNIFIED_STATUSES)}, "
                f"got {self.status!r}"
            )
        if self.severity not in _VALID_UNIFIED_SEVERITIES:
            raise ValueError(
                f"severity must be one of {sorted(_VALID_UNIFIED_SEVERITIES)}, "
                f"got {self.severity!r}"
            )
        if self.streak < 0:
            raise ValueError(
                f"streak must be >= 0, got {self.streak}"
            )
        # Defensive copy of mutable containers
        object.__setattr__(self, "categories", list(self.categories))
        object.__setattr__(self, "reasons", list(self.reasons))


# ── 2.9.3 — DriftConfirmationState ────────────────────────────────────────────


@dataclass(frozen=True)
class DriftConfirmationState:
    """
    Phase 2.9.3 — Stabilised drift decision after multi‑cycle confirmation.

    Produced by the drift confirmation engine (``confirm_drift()``) to
    prevent oscillation and accumulate confidence across cycles.

    Pure, deterministic, JSON‑safe — never mutates inputs.

    ``confirmed``
        ``True`` when drift has survived the confirmation thresholds:
        streak ≥ 2 for minor/major, streak ≥ 1 for catastrophic.
    ``severity``
        The current severity if confirmed, else ``"minor"``.
    ``confidence``
        Accumulated confidence: ``min(1.0, current + previous × 0.5)``.
    ``streak``
        How many consecutive cycles the same drift status has been observed.
    ``hysteresis``
        Value in [0.0, 1.0] that prevents rapid flip‑flopping.  Rises when
        drift is confirmed (+0.2) and decays otherwise (−0.1).  When
        ``current.confidence < hysteresis``, drift is suppressed.
    ``history``
        Appended copy of the current ``UnifiedDriftClassification`` across
        cycles.  Defensively copied at construction.
    """

    confirmed: bool
    severity: Literal["minor", "major", "catastrophic"]
    confidence: float
    streak: int
    hysteresis: float
    history: List[UnifiedDriftClassification]

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        if self.hysteresis < 0.0 or self.hysteresis > 1.0:
            raise ValueError(
                f"hysteresis must be in [0.0, 1.0], got {self.hysteresis}"
            )
        if self.severity not in _VALID_UNIFIED_SEVERITIES:
            raise ValueError(
                f"severity must be one of {sorted(_VALID_UNIFIED_SEVERITIES)}, "
                f"got {self.severity!r}"
            )
        if self.streak < 0:
            raise ValueError(
                f"streak must be >= 0, got {self.streak}"
            )
        # Defensive copy of mutable history list
        object.__setattr__(self, "history", list(self.history))


# ── 2.9.4 — DriftRecoveryDecision ────────────────────────────────────────────

_VALID_RECOVERY_ACTIONS = frozenset({
    "none",
    "repair",
    "replan",
    "regen_segment",
    "regen_plan",
    "regen_subgoal",
    "full_reset",
})


@dataclass(frozen=True)
class DriftRecoveryDecision:
    """
    Phase 2.9.4 — Deterministic recovery decision from confirmed drift.

    Produced by the drift recovery engine (``recover_from_drift()``) to
    choose the appropriate recovery path: repair, replan, or escalate to
    regeneration / full reset for catastrophic drift.

    Pure, deterministic, JSON‑safe — never mutates inputs.

    ``action``
        The recovery action to take.  One of ``"none"``, ``"repair"``,
        ``"replan"``, ``"regen_segment"``, ``"regen_plan"``,
        ``"regen_subgoal"``, or ``"full_reset"``.

    ``severity``
        The confirmed drift severity: ``"minor"``, ``"major"``, or
        ``"catastrophic"``.

    ``confidence``
        Accumulated confidence from the confirmation state, in [0.0, 1.0].

    ``streak``
        Consecutive cycles of confirmed drift.

    ``hysteresis``
        Hysteresis value from the confirmation state, in [0.0, 1.0].

    ``reasons``
        Deterministic list of JSON‑safe reason strings explaining the
        decision.  Defensively copied at construction.
    """

    action: Literal[
        "none",
        "repair",
        "replan",
        "regen_segment",
        "regen_plan",
        "regen_subgoal",
        "full_reset",
    ]
    severity: Literal["minor", "major", "catastrophic"]
    confidence: float
    streak: int
    hysteresis: float
    reasons: List[str]

    def __post_init__(self) -> None:
        if self.action not in _VALID_RECOVERY_ACTIONS:
            raise ValueError(
                f"action must be one of {sorted(_VALID_RECOVERY_ACTIONS)}, "
                f"got {self.action!r}"
            )
        if self.severity not in _VALID_UNIFIED_SEVERITIES:
            raise ValueError(
                f"severity must be one of {sorted(_VALID_UNIFIED_SEVERITIES)}, "
                f"got {self.severity!r}"
            )
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        if self.hysteresis < 0.0 or self.hysteresis > 1.0:
            raise ValueError(
                f"hysteresis must be in [0.0, 1.0], got {self.hysteresis}"
            )
        if self.streak < 0:
            raise ValueError(
                f"streak must be >= 0, got {self.streak}"
            )
        # Defensive copy of reasons list
        object.__setattr__(self, "reasons", list(self.reasons))
