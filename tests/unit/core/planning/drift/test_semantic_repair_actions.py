"""
Tests for Phase 2.8.4 — Semantic Repair Actions.

Covers:
  - repair_semantic_drift() pure function
  - SemanticRepairPlan dataclass validation
  - Category → action mapping (contradictprior_behaviour, contradictplan,
    contradictsubgoal, contradictmemory)
  - Multiple categories → sorted actions
  - Confidence and streak propagation
  - Determinism and non-mutation invariants
"""
from __future__ import annotations

import json
from typing import List

import pytest

from src.core.planning.drift.semantic_signal_types import (
    SemanticDriftClassification,
    SemanticRepairPlan,
)
from src.core.planning.drift.semantic_repair_actions import (
    repair_semantic_drift,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _classification(
    *,
    status: str = "no_drift",
    categories: List[str] | None = None,
    confidence: float = 0.0,
    streak: int = 0,
) -> SemanticDriftClassification:
    """Build a SemanticDriftClassification for testing."""
    return SemanticDriftClassification(
        status=status,  # type: ignore[arg-type]
        categories=categories or [],
        confidence=confidence,
        reasons=[],
        streak=streak,
    )


# ============================================================================
# SemanticRepairPlan dataclass
# ============================================================================


class TestSemanticRepairPlan:
    """Tests for the SemanticRepairPlan dataclass itself."""

    def test_no_repair_construction(self) -> None:
        plan = SemanticRepairPlan(
            needs_repair=False,
            repair_actions=[],
            confidence=0.0,
            categories=[],
            streak=0,
        )
        assert plan.needs_repair is False
        assert plan.repair_actions == []
        assert plan.confidence == 0.0
        assert plan.categories == []
        assert plan.streak == 0

    def test_repair_construction(self) -> None:
        plan = SemanticRepairPlan(
            needs_repair=True,
            repair_actions=["rewrite step"],
            confidence=0.7,
            categories=["contradictprior_behaviour"],
            streak=3,
        )
        assert plan.needs_repair is True
        assert plan.repair_actions == ["rewrite step"]
        assert plan.confidence == 0.7
        assert plan.categories == ["contradictprior_behaviour"]
        assert plan.streak == 3

    def test_frozen(self) -> None:
        plan = SemanticRepairPlan(
            needs_repair=False,
            repair_actions=[],
            confidence=0.0,
            categories=[],
            streak=0,
        )
        with pytest.raises(Exception):
            plan.needs_repair = True  # type: ignore[misc]

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            SemanticRepairPlan(
                needs_repair=False,
                repair_actions=[],
                confidence=1.5,
                categories=[],
                streak=0,
            )

    def test_confidence_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            SemanticRepairPlan(
                needs_repair=False,
                repair_actions=[],
                confidence=-0.1,
                categories=[],
                streak=0,
            )

    def test_negative_streak_raises(self) -> None:
        with pytest.raises(ValueError, match="streak"):
            SemanticRepairPlan(
                needs_repair=False,
                repair_actions=[],
                confidence=0.0,
                categories=[],
                streak=-1,
            )

    def test_unknown_category_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown category"):
            SemanticRepairPlan(
                needs_repair=True,
                repair_actions=["something"],
                confidence=0.5,
                categories=["bogus"],
                streak=1,
            )

    def test_non_string_action_raises(self) -> None:
        with pytest.raises(ValueError, match="repair action"):
            SemanticRepairPlan(
                needs_repair=True,
                repair_actions=[42],  # type: ignore[list-item]
                confidence=0.5,
                categories=["contradictplan"],
                streak=1,
            )

    def test_categories_defensive_copy(self) -> None:
        cats = ["contradictplan"]
        plan = SemanticRepairPlan(
            needs_repair=True,
            repair_actions=["rewrite plan"],
            confidence=0.7,
            categories=cats,
            streak=1,
        )
        cats.append("contradictsubgoal")
        assert plan.categories == ["contradictplan"]

    def test_repair_actions_defensive_copy(self) -> None:
        actions = ["rewrite plan"]
        plan = SemanticRepairPlan(
            needs_repair=True,
            repair_actions=actions,
            confidence=0.7,
            categories=["contradictplan"],
            streak=1,
        )
        actions.append("rewrite subgoal")
        assert plan.repair_actions == ["rewrite plan"]


# ============================================================================
# repair_semantic_drift — core logic
# ============================================================================


class TestRepairSemanticDrift:
    """Tests for the repair_semantic_drift() pure function."""

    # ── no_drift → no repair ──────────────────────────────────────────

    def test_no_drift_returns_no_repair(self) -> None:
        clf = _classification(status="no_drift")
        plan = repair_semantic_drift(clf)
        assert plan.needs_repair is False
        assert plan.repair_actions == []
        assert plan.confidence == 0.0
        assert plan.categories == []
        assert plan.streak == 0

    # ── single category → correct action ──────────────────────────────

    def test_contradictprior_behaviour_action(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictprior_behaviour"],
            confidence=0.7,
            streak=2,
        )
        plan = repair_semantic_drift(clf)
        assert plan.needs_repair is True
        assert plan.repair_actions == ["rewrite step"]

    def test_contradictplan_action(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.8,
            streak=1,
        )
        plan = repair_semantic_drift(clf)
        assert plan.repair_actions == ["rewrite plan"]

    def test_contradictsubgoal_action(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictsubgoal"],
            confidence=0.9,
            streak=3,
        )
        plan = repair_semantic_drift(clf)
        assert plan.repair_actions == ["rewrite subgoal"]

    def test_contradictmemory_action(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictmemory"],
            confidence=1.0,
            streak=4,
        )
        plan = repair_semantic_drift(clf)
        assert plan.repair_actions == ["rewrite segment"]

    # ── multiple categories → sorted actions ──────────────────────────

    def test_multiple_categories_sorted_actions(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=[
                "contradictplan",
                "contradictprior_behaviour",
                "contradictsubgoal",
            ],
            confidence=1.0,
            streak=2,
        )
        plan = repair_semantic_drift(clf)
        # Categories sorted alphabetically → actions follow same order
        assert plan.repair_actions == [
            "rewrite plan",         # contradictplan
            "rewrite step",         # contradictprior_behaviour
            "rewrite subgoal",      # contradictsubgoal
        ]

    def test_all_four_categories(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=[
                "contradictmemory",
                "contradictplan",
                "contradictprior_behaviour",
                "contradictsubgoal",
            ],
            confidence=1.0,
            streak=5,
        )
        plan = repair_semantic_drift(clf)
        assert plan.repair_actions == [
            "rewrite segment",   # contradictmemory
            "rewrite plan",      # contradictplan
            "rewrite step",      # contradictprior_behaviour
            "rewrite subgoal",   # contradictsubgoal
        ]

    # ── confidence propagation ────────────────────────────────────────

    def test_confidence_copied_from_classification(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictsubgoal"],
            confidence=0.95,
            streak=1,
        )
        plan = repair_semantic_drift(clf)
        assert plan.confidence == 0.95

    def test_confidence_zero_on_no_drift(self) -> None:
        clf = _classification(status="no_drift", confidence=0.0)
        plan = repair_semantic_drift(clf)
        assert plan.confidence == 0.0

    # ── streak propagation ────────────────────────────────────────────

    def test_streak_copied_from_classification(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.7,
            streak=7,
        )
        plan = repair_semantic_drift(clf)
        assert plan.streak == 7

    def test_streak_zero_on_no_drift(self) -> None:
        clf = _classification(status="no_drift", streak=0)
        plan = repair_semantic_drift(clf)
        assert plan.streak == 0

    # ── determinism ───────────────────────────────────────────────────

    def test_deterministic_output(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictmemory", "contradictplan"],
            confidence=0.85,
            streak=2,
        )
        p1 = repair_semantic_drift(clf)
        p2 = repair_semantic_drift(clf)
        assert p1.needs_repair == p2.needs_repair
        assert p1.repair_actions == p2.repair_actions
        assert p1.confidence == p2.confidence
        assert p1.categories == p2.categories
        assert p1.streak == p2.streak

    # ── non-mutation invariants ───────────────────────────────────────

    def test_does_not_mutate_classification(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.8,
            streak=4,
        )
        repair_semantic_drift(clf)
        assert clf.status == "semantic_drift"
        assert clf.categories == ["contradictplan"]
        assert clf.confidence == 0.8
        assert clf.streak == 4

    # ── JSON safety ───────────────────────────────────────────────────

    def test_result_is_json_safe(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictplan", "contradictsubgoal"],
            confidence=1.0,
            streak=2,
        )
        plan = repair_semantic_drift(clf)
        dumped = json.dumps({
            "needs_repair": plan.needs_repair,
            "repair_actions": plan.repair_actions,
            "confidence": plan.confidence,
            "categories": plan.categories,
            "streak": plan.streak,
        })
        assert isinstance(dumped, str)
