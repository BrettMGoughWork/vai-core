"""
Phase 2.8 — Semantic Signal Types
=================================

``SemanticMismatch`` (2.8.1)
    A deterministic finding that a segment output may be semantically
    misaligned with a validation target.

``SemanticDriftSignal`` (2.8.2)
    A structured drift signal mapped from a ``SemanticMismatch``.
    Mutually exclusive signal types: contradictplan, contradictsubgoal,
    contradictmemory, contradictprior_behaviour.

``SemanticDriftClassification`` (2.8.3)
    A deterministic classification of semantic drift across cycles,
    with categories, confidence, and streak tracking.

All dataclasses are frozen, JSON‑safe, and pure.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Literal

from src.core.types.json_pure import ensure_json_pure

# ── 2.8.1 — SemanticMismatch ──────────────────────────────────────────────────

SemanticMismatchType = Literal[
    "step_mismatch",
    "plan_mismatch",
    "subgoal_mismatch",
    "memory_mismatch",
]


@dataclass(frozen=True)
class SemanticMismatch:
    """
    A deterministic finding that a segment output may be semantically
    misaligned with one of the four validation targets.

    Fields
    ------
    type:
        Which validation dimension produced the mismatch.
        One of ``step_mismatch``, ``plan_mismatch``, ``subgoal_mismatch``,
        ``memory_mismatch``.
    confidence:
        Heuristic confidence in [0.0, 1.0].
    details:
        JSON‑safe dict with human‑readable mismatch description.
        Deep‑copied at construction to prevent external mutation.
    """
    type: SemanticMismatchType
    confidence: float
    details: Dict[str, Any]

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        ensure_json_pure(self.details)
        object.__setattr__(self, "details", copy.deepcopy(self.details))


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


# ── 2.8.3 — SemanticDriftClassification ───────────────────────────────────────


_VALID_SEMANTIC_STATUSES = frozenset({"no_drift", "semantic_drift"})

_VALID_SEMANTIC_CATEGORIES = frozenset({
    "contradictplan",
    "contradictsubgoal",
    "contradictmemory",
    "contradictprior_behaviour",
})


@dataclass(frozen=True)
class SemanticDriftClassification:
    """
    Phase 2.8.3 — Classification of semantic drift across cycles.

    Maps a list of ``SemanticDriftSignal``\\ s into a deterministic
    classification with categories, confidence, and streak tracking.

    Pure, deterministic, JSON‑safe — never mutates inputs.

    ``status``
        ``"no_drift"`` when signals is empty, ``"semantic_drift"`` otherwise.
    ``categories``
        Sorted list of unique signal type strings
        (e.g. ``["contradictplan", "contradictsubgoal"]``).
    ``confidence``
        ``max(signal.confidence) + 0.1 × streak``, capped at 1.0.
    ``reasons``
        Defensive copy of the ``SemanticDriftSignal``\\ s that triggered the
        classification.
    ``streak``
        Multi‑cycle confirmation counter.  Increments when the status matches
        the previous classification; resets to 1 otherwise.
    """

    status: Literal["no_drift", "semantic_drift"]
    categories: List[str]
    confidence: float
    reasons: List[SemanticDriftSignal]
    streak: int

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be 0.0–1.0, got {self.confidence}"
            )
        if self.status not in _VALID_SEMANTIC_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_VALID_SEMANTIC_STATUSES)}, "
                f"got {self.status!r}"
            )
        if self.streak < 0:
            raise ValueError(
                f"streak must be >= 0, got {self.streak}"
            )
        # Validate all categories are in the known set
        for cat in self.categories:
            if cat not in _VALID_SEMANTIC_CATEGORIES:
                raise ValueError(
                    f"unknown category {cat!r}; must be one of "
                    f"{sorted(_VALID_SEMANTIC_CATEGORIES)}"
                )
        # Defensive copy of mutable containers
        object.__setattr__(self, "categories", list(self.categories))
        object.__setattr__(self, "reasons", list(self.reasons))


# ── 2.8.4 — SemanticRepairPlan ────────────────────────────────────────────────


_SEMANTIC_CATEGORY_REPAIR_ACTION: Dict[str, str] = {
    "contradictprior_behaviour": "rewrite step",
    "contradictplan": "rewrite plan",
    "contradictsubgoal": "rewrite subgoal",
    "contradictmemory": "rewrite segment",
}


@dataclass(frozen=True)
class SemanticRepairPlan:
    """
    Phase 2.8.4 — Repair plan produced from a semantic drift classification.

    Describes how Stratum‑2 should respond when semantic drift is detected.
    Pure, deterministic, JSON‑safe — not actual rewriting.

    ``needs_repair``
        ``True`` when ``classification.status == "semantic_drift"``.
    ``repair_actions``
        Sorted list of human‑readable, JSON‑safe action strings derived from
        categories (e.g. ``"rewrite plan"``).
    ``confidence``
        Copied from the classification (0.0–1.0).
    ``categories``
        Defensive copy of the classification's categories.
    ``streak``
        Copied from the classification.
    """

    needs_repair: bool
    repair_actions: List[str]
    confidence: float
    categories: List[str]
    streak: int

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be 0.0–1.0, got {self.confidence}"
            )
        if self.streak < 0:
            raise ValueError(
                f"streak must be >= 0, got {self.streak}"
            )
        for cat in self.categories:
            if cat not in _VALID_SEMANTIC_CATEGORIES:
                raise ValueError(
                    f"unknown category {cat!r}; must be one of "
                    f"{sorted(_VALID_SEMANTIC_CATEGORIES)}"
                )
        for action in self.repair_actions:
            if not isinstance(action, str):
                raise ValueError(
                    f"repair action must be a string, got {type(action)}"
                )
        # Defensive copy of mutable containers
        object.__setattr__(self, "categories", list(self.categories))
        object.__setattr__(self, "repair_actions", list(self.repair_actions))
