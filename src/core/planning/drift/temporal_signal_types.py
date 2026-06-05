"""
Phase 2.7 — Temporal Signal Types
=================================

``ProgressSignal`` (2.7.1) represents a progress assessment from comparing
two consecutive ``SegmentMemoryRecord`` instances.

``TemporalDriftSignal`` (2.7.2) represents a multi‑cycle temporal anomaly
such as no progress, repetition, oscillation, or regression.

``TemporalDriftClassification`` (2.7.3) represents the classified temporal
health of a segment, with categories, confidence, and streak tracking.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Literal

from src.core.types.json_pure import ensure_json_pure


# ── 2.7.1 — ProgressSignal ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ProgressSignal:
    """
    Progress assessment from temporal comparison of segment records.

    Pure, deterministic, JSON‑safe — never mutates inputs.
    """

    status: Literal["steady", "stalled", "regressed"]
    confidence: float
    reasons: List[str]

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be 0.0–1.0, got {self.confidence}"
            )
        if self.status not in ("steady", "stalled", "regressed"):
            raise ValueError(
                f"status must be 'steady', 'stalled', or 'regressed', "
                f"got {self.status!r}"
            )
        # Defensive copy and JSON validation
        ensure_json_pure(self.reasons)
        object.__setattr__(self, "reasons", list(self.reasons))


# ── 2.7.2 — TemporalDriftSignal ─────────────────────────────────────────────


_TEMPORAL_DRIFT_TYPES = frozenset(
    {"no_progress", "repetition", "oscillation", "regression"}
)


@dataclass(frozen=True)
class TemporalDriftSignal:
    """
    Multi‑cycle temporal anomaly detected from segment record comparison.

    Pure, deterministic, JSON‑safe — never mutates inputs.
    """

    type: Literal["no_progress", "repetition", "oscillation", "regression"]
    confidence: float
    details: Dict[str, Any]

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be 0.0–1.0, got {self.confidence}"
            )
        if self.type not in _TEMPORAL_DRIFT_TYPES:
            raise ValueError(
                f"type must be one of {sorted(_TEMPORAL_DRIFT_TYPES)}, "
                f"got {self.type!r}"
            )
        # Defensive copy and JSON validation
        details_copy = copy.deepcopy(self.details)
        ensure_json_pure(details_copy)
        object.__setattr__(self, "details", details_copy)


# ── 2.7.3 — TemporalDriftClassification ──────────────────────────────────────


_TEMPORAL_CATEGORY_MAP: Dict[str, str] = {
    "no_progress": "stall",
    "repetition": "repetition",
    "oscillation": "oscillation",
    "regression": "regression",
}

_VALID_TEMPORAL_STATUSES = frozenset({"no_drift", "temporal_drift"})


@dataclass(frozen=True)
class TemporalDriftClassification:
    """
    Phase 2.7.3 — Classification of temporal drift across cycles.

    Maps a list of ``TemporalDriftSignal``\\ s into a deterministic
    classification with categories, confidence, and streak tracking.

    Pure, deterministic, JSON‑safe — never mutates inputs.

    ``status``
        ``"no_drift"`` when signals is empty, ``"temporal_drift"`` otherwise.
    ``categories``
        Sorted list of category names derived from signal types
        (e.g. ``["oscillation", "stall"]``).
    ``confidence``
        ``max(signal.confidence) + 0.1 × streak``, capped at 1.0.
    ``reasons``
        Defensive copy of the ``TemporalDriftSignal``\\ s that triggered the
        classification.
    ``streak``
        Multi‑cycle confirmation counter.  Increments when the status matches
        the previous classification; resets to 1 otherwise.
    """

    status: Literal["no_drift", "temporal_drift"]
    categories: List[str]
    confidence: float
    reasons: List[TemporalDriftSignal]
    streak: int

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be 0.0–1.0, got {self.confidence}"
            )
        if self.status not in _VALID_TEMPORAL_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_VALID_TEMPORAL_STATUSES)}, "
                f"got {self.status!r}"
            )
        if self.streak < 0:
            raise ValueError(
                f"streak must be >= 0, got {self.streak}"
            )
        # Validate all categories are in the known map
        for cat in self.categories:
            if cat not in _TEMPORAL_CATEGORY_MAP.values():
                raise ValueError(
                    f"unknown category {cat!r}; must be one of "
                    f"{sorted(_TEMPORAL_CATEGORY_MAP.values())}"
                )
        # Defensive copy of mutable containers
        object.__setattr__(self, "categories", list(self.categories))
        object.__setattr__(self, "reasons", list(self.reasons))
