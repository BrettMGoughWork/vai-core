"""
Phase 2.7.1 — Temporal Signal Types
==================================

``ProgressSignal`` is a frozen, JSON‑safe dataclass that represents a
progress assessment from comparing two consecutive ``SegmentMemoryRecord``
instances.

Fields
------
status: Literal["steady", "stalled", "regressed"]
    The progress classification.
confidence: float (0.0–1.0)
    Confidence in the classification.  Fixed per status:
      - steady    → 0.7
      - stalled   → 0.5
      - regressed → 0.9
reasons: List[str]
    Human‑readable, deterministic strings describing what changed between
    the two records.  Always sorted for determinism.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import List, Literal

from src.core.types.json_pure import ensure_json_pure


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
