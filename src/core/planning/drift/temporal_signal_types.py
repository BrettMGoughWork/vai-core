"""
Phase 2.7 — Temporal Signal Types
=================================

``ProgressSignal`` (2.7.1) represents a progress assessment from comparing
two consecutive ``SegmentMemoryRecord`` instances.

``TemporalDriftSignal`` (2.7.2) represents a multi‑cycle temporal anomaly
such as no progress, repetition, oscillation, or regression.
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
