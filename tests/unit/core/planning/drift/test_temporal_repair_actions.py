"""
Tests for Phase 2.7.4 — Temporal Repair Actions.

Covers:
  - repair_temporal_drift() pure function
  - TemporalRepairPlan dataclass validation
  - Category → action mapping (stall, repetition, oscillation, regression)
  - Multiple categories → sorted actions
  - Confidence and streak propagation
  - Determinism and non-mutation invariants
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List

import pytest

from src.core.planning.drift.temporal_signal_types import (
    TemporalDriftClassification,
    TemporalRepairPlan,
)
from src.core.planning.drift.temporal_repair_actions import (
    repair_temporal_drift,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _classification(
    *,
    status: str = "no_drift",
    categories: List[str] | None = None,
    confidence: float = 0.0,
    streak: int = 0,
) -> TemporalDriftClassification:
    """Build a TemporalDriftClassification for testing."""
    return TemporalDriftClassification(
        status=status,  # type: ignore[arg-type]
        categories=categories or [],
        confidence=confidence,
        reasons=[],
        streak=streak,
    )


# ============================================================================
# TemporalRepairPlan dataclass
# ============================================================================


class TestTemporalRepairPlan:
    """Tests for the TemporalRepairPlan dataclass itself."""

    def test_no_repair_construction(self) -> None:
        plan = TemporalRepairPlan(
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
        plan = TemporalRepairPlan(
            needs_repair=True,
            repair_actions=["regenerate segment"],
            confidence=0.7,
            categories=["stall"],
            streak=3,
        )
        assert plan.needs_repair is True
        assert plan.repair_actions == ["regenerate segment"]
        assert plan.confidence == 0.7
        assert plan.categories == ["stall"]
        assert plan.streak == 3

    def test_frozen(self) -> None:
        plan = TemporalRepairPlan(
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
            TemporalRepairPlan(
                needs_repair=False,
                repair_actions=[],
                confidence=1.5,
                categories=[],
                streak=0,
            )

    def test_confidence_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            TemporalRepairPlan(
                needs_repair=False,
                repair_actions=[],
                confidence=-0.1,
                categories=[],
                streak=0,
            )

    def test_negative_streak_raises(self) -> None:
        with pytest.raises(ValueError, match="streak"):
            TemporalRepairPlan(
                needs_repair=False,
                repair_actions=[],
                confidence=0.0,
                categories=[],
                streak=-1,
            )

    def test_unknown_category_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown category"):
            TemporalRepairPlan(
                needs_repair=True,
                repair_actions=["something"],
                confidence=0.5,
                categories=["bogus"],
                streak=1,
            )

    def test_non_string_action_raises(self) -> None:
        with pytest.raises(ValueError, match="repair action"):
            TemporalRepairPlan(
                needs_repair=True,
                repair_actions=[42],  # type: ignore[list-item]
                confidence=0.5,
                categories=["stall"],
                streak=1,
            )

    def test_categories_defensive_copy(self) -> None:
        cats = ["stall"]
        plan = TemporalRepairPlan(
            needs_repair=True,
            repair_actions=["regenerate segment"],
            confidence=0.7,
            categories=cats,
            streak=1,
        )
        cats.append("oscillation")
        assert plan.categories == ["stall"]

    def test_repair_actions_defensive_copy(self) -> None:
        actions = ["regenerate segment"]
        plan = TemporalRepairPlan(
            needs_repair=True,
            repair_actions=actions,
            confidence=0.7,
            categories=["stall"],
            streak=1,
        )
        actions.append("re-decompose subgoal")
        assert plan.repair_actions == ["regenerate segment"]


# ============================================================================
# repair_temporal_drift — core logic
# ============================================================================


class TestRepairTemporalDrift:
    """Tests for the repair_temporal_drift() pure function."""

    # ── no_drift → no repair ────────────────────────────────────────────

    def test_no_drift_returns_no_repair(self) -> None:
        clf = _classification(status="no_drift")
        plan = repair_temporal_drift(clf)
        assert plan.needs_repair is False
        assert plan.repair_actions == []
        assert plan.confidence == 0.0
        assert plan.categories == []
        assert plan.streak == 0

    # ── single category → correct action ────────────────────────────────

    def test_stall_action(self) -> None:
        clf = _classification(
            status="temporal_drift", categories=["stall"], confidence=0.7, streak=2
        )
        plan = repair_temporal_drift(clf)
        assert plan.needs_repair is True
        assert plan.repair_actions == ["regenerate segment"]

    def test_repetition_action(self) -> None:
        clf = _classification(
            status="temporal_drift", categories=["repetition"], confidence=0.8, streak=1
        )
        plan = repair_temporal_drift(clf)
        assert plan.repair_actions == ["reset segment state"]

    def test_oscillation_action(self) -> None:
        clf = _classification(
            status="temporal_drift", categories=["oscillation"], confidence=0.9, streak=3
        )
        plan = repair_temporal_drift(clf)
        assert plan.repair_actions == ["re-decompose subgoal"]

    def test_regression_action(self) -> None:
        clf = _classification(
            status="temporal_drift", categories=["regression"], confidence=1.0, streak=4
        )
        plan = repair_temporal_drift(clf)
        assert plan.repair_actions == ["regenerate plan"]

    # ── multiple categories → sorted actions ────────────────────────────

    def test_multiple_categories_sorted_actions(self) -> None:
        clf = _classification(
            status="temporal_drift",
            categories=["oscillation", "regression", "stall"],
            confidence=1.0,
            streak=2,
        )
        plan = repair_temporal_drift(clf)
        # Categories are alphabetical → repair actions follow same order
        assert plan.repair_actions == [
            "re-decompose subgoal",   # oscillation
            "regenerate plan",        # regression
            "regenerate segment",     # stall
        ]

    def test_all_four_categories(self) -> None:
        clf = _classification(
            status="temporal_drift",
            categories=["oscillation", "regression", "repetition", "stall"],
            confidence=1.0,
            streak=5,
        )
        plan = repair_temporal_drift(clf)
        assert plan.repair_actions == [
            "re-decompose subgoal",   # oscillation
            "regenerate plan",        # regression
            "reset segment state",    # repetition
            "regenerate segment",     # stall
        ]

    # ── confidence propagation ──────────────────────────────────────────

    def test_confidence_copied_from_classification(self) -> None:
        clf = _classification(
            status="temporal_drift",
            categories=["regression"],
            confidence=0.95,
            streak=1,
        )
        plan = repair_temporal_drift(clf)
        assert plan.confidence == 0.95

    def test_confidence_zero_on_no_drift(self) -> None:
        clf = _classification(status="no_drift", confidence=0.0)
        plan = repair_temporal_drift(clf)
        assert plan.confidence == 0.0

    # ── streak propagation ──────────────────────────────────────────────

    def test_streak_copied_from_classification(self) -> None:
        clf = _classification(
            status="temporal_drift",
            categories=["stall"],
            confidence=0.7,
            streak=7,
        )
        plan = repair_temporal_drift(clf)
        assert plan.streak == 7

    def test_streak_zero_on_no_drift(self) -> None:
        clf = _classification(status="no_drift", streak=0)
        plan = repair_temporal_drift(clf)
        assert plan.streak == 0

    # ── determinism ─────────────────────────────────────────────────────

    def test_deterministic_output(self) -> None:
        clf = _classification(
            status="temporal_drift",
            categories=["oscillation", "stall"],
            confidence=0.85,
            streak=2,
        )
        p1 = repair_temporal_drift(clf)
        p2 = repair_temporal_drift(clf)
        assert p1.needs_repair == p2.needs_repair
        assert p1.repair_actions == p2.repair_actions
        assert p1.confidence == p2.confidence
        assert p1.categories == p2.categories
        assert p1.streak == p2.streak

    # ── non-mutation invariants ─────────────────────────────────────────

    def test_does_not_mutate_classification(self) -> None:
        clf = _classification(
            status="temporal_drift",
            categories=["repetition"],
            confidence=0.8,
            streak=4,
        )
        repair_temporal_drift(clf)
        assert clf.status == "temporal_drift"
        assert clf.categories == ["repetition"]
        assert clf.confidence == 0.8
        assert clf.streak == 4

    # ── JSON safety ─────────────────────────────────────────────────────

    def test_result_is_json_safe(self) -> None:
        clf = _classification(
            status="temporal_drift",
            categories=["oscillation", "regression"],
            confidence=1.0,
            streak=2,
        )
        plan = repair_temporal_drift(clf)
        dumped = json.dumps({
            "needs_repair": plan.needs_repair,
            "repair_actions": plan.repair_actions,
            "confidence": plan.confidence,
            "categories": plan.categories,
            "streak": plan.streak,
        })
        assert isinstance(dumped, str)
