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
