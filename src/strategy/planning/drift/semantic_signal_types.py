"""
Phase 2.8 — Semantic Signal Types
=================================

``SemanticDriftSignal`` (2.8.2)
    A structured drift signal mapped from a semantic mismatch.
    Mutually exclusive signal types: contradictplan, contradictsubgoal,
    contradictmemory, contradictprior_behaviour.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Literal

from src.strategy.types.json_pure import ensure_json_pure

# ── 2.8.2 — SemanticDriftSignal ───────────────────────────────────────────────


_SEMANTIC_DRIFT_TYPES = frozenset(
    {"contradictplan", "contradictsubgoal", "contradictmemory",
     "contradictprior_behaviour"}
)


@dataclass(frozen=True)
class SemanticDriftSignal:
    """
    A structured, deterministic drift signal emitted from a semantic mismatch.

    Each signal type corresponds to a single mismatch source:

    - ``contradictplan`` — plan_mismatch
    - ``contradictsubgoal`` — subgoal_mismatch
    - ``contradictmemory`` — memory_mismatch
    - ``contradictprior_behaviour`` — step_mismatch

    Pure, deterministic, JSON‑safe — never mutates inputs.
    """

    type: Literal[
        "contradictplan", "contradictsubgoal", "contradictmemory",
        "contradictprior_behaviour",
    ]
    confidence: float
    details: Dict[str, Any]

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be 0.0–1.0, got {self.confidence}"
            )
        if self.type not in _SEMANTIC_DRIFT_TYPES:
            raise ValueError(
                f"type must be one of {sorted(_SEMANTIC_DRIFT_TYPES)}, "
                f"got {self.type!r}"
            )
        # Defensive copy and JSON validation
        details_copy = copy.deepcopy(self.details)
        ensure_json_pure(details_copy)
        object.__setattr__(self, "details", details_copy)
