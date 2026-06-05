"""
Tests for Phase 2.8.3 — Semantic Drift Classifier.

Covers:
  - classify_semantic_drift() pure function
  - SemanticDriftClassification dataclass validation
  - Category derivation from signal types
  - Confidence formula (max signal + streak bonus, capped at 1.0)
  - Streak logic (first cycle, increment, reset)
  - Determinism and non-mutation invariants
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

import pytest

from src.core.planning.drift.semantic_signal_types import (
    SemanticDriftClassification,
    SemanticDriftSignal,
)
from src.core.planning.drift.semantic_drift_classifier import (
    classify_semantic_drift,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _make_signal(
    signal_type: str = "contradictplan",
    confidence: float = 0.7,
    details: Dict[str, Any] | None = None,
) -> SemanticDriftSignal:
    """Create a SemanticDriftSignal with convenient defaults."""
    return SemanticDriftSignal(
        type=signal_type,  # type: ignore[arg-type]
        confidence=confidence,
        details=details or {},
    )


# ============================================================================
# SemanticDriftClassification dataclass
# ============================================================================


class TestSemanticDriftClassification:
    """Tests for the SemanticDriftClassification dataclass itself."""

    def test_no_drift_construction(self) -> None:
        c = SemanticDriftClassification(
            status="no_drift",
            categories=[],
            confidence=0.0,
            reasons=[],
            streak=0,
        )
        assert c.status == "no_drift"
        assert c.categories == []
        assert c.confidence == 0.0
        assert c.reasons == []
        assert c.streak == 0

    def test_semantic_drift_construction(self) -> None:
        sig = _make_signal("contradictplan", confidence=0.8)
        c = SemanticDriftClassification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.9,
            reasons=[sig],
            streak=2,
        )
        assert c.status == "semantic_drift"
        assert c.categories == ["contradictplan"]
        assert c.confidence == 0.9
        assert c.reasons == [sig]
        assert c.streak == 2

    def test_frozen(self) -> None:
        c = SemanticDriftClassification(
            status="no_drift",
            categories=[],
            confidence=0.0,
            reasons=[],
            streak=0,
        )
        with pytest.raises(Exception):
            c.streak = 1  # type: ignore[misc]

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            SemanticDriftClassification(
                status="no_drift",
                categories=[],
                confidence=1.5,
                reasons=[],
                streak=0,
            )

    def test_confidence_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            SemanticDriftClassification(
                status="no_drift",
                categories=[],
                confidence=-0.1,
                reasons=[],
                streak=0,
            )

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValueError, match="status"):
            SemanticDriftClassification(
                status="invalid",  # type: ignore[arg-type]
                categories=[],
                confidence=0.5,
                reasons=[],
                streak=0,
            )

    def test_negative_streak_raises(self) -> None:
        with pytest.raises(ValueError, match="streak"):
            SemanticDriftClassification(
                status="no_drift",
                categories=[],
                confidence=0.0,
                reasons=[],
                streak=-1,
            )

    def test_unknown_category_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown category"):
            SemanticDriftClassification(
                status="semantic_drift",
                categories=["bogus_category"],
                confidence=0.5,
                reasons=[],
                streak=1,
            )

    def test_categories_is_defensive_copy(self) -> None:
        """Mutating the list passed in doesn't affect the frozen instance."""
        cats = ["contradictplan"]
        c = SemanticDriftClassification(
            status="semantic_drift",
            categories=cats,
            confidence=0.5,
            reasons=[],
            streak=1,
        )
        cats.append("contradictsubgoal")
        assert c.categories == ["contradictplan"]

    def test_reasons_is_defensive_copy(self) -> None:
        """Mutating the list passed in doesn't affect the frozen instance."""
        sig = _make_signal("contradictmemory", confidence=0.6)
        reasons = [sig]
        c = SemanticDriftClassification(
            status="semantic_drift",
            categories=["contradictmemory"],
            confidence=0.6,
            reasons=reasons,
            streak=1,
        )
        reasons.append(_make_signal("contradictplan"))
        assert len(c.reasons) == 1


# ============================================================================
# classify_semantic_drift — core logic
# ============================================================================


class TestClassifySemanticDrift:
    """Tests for the classify_semantic_drift() pure function."""

    # ── no signals → no_drift ──────────────────────────────────────────

    def test_empty_signals_returns_no_drift(self) -> None:
        result = classify_semantic_drift([])
        assert result.status == "no_drift"
        assert result.categories == []
        assert result.confidence == 0.0
        assert result.reasons == []
        assert result.streak == 0

    # ── single signal → correct category ───────────────────────────────

    def test_contradictplan_signal(self) -> None:
        sig = _make_signal("contradictplan", confidence=0.8)
        result = classify_semantic_drift([sig])
        assert result.status == "semantic_drift"
        assert result.categories == ["contradictplan"]
        assert len(result.reasons) == 1
        assert result.streak == 1

    def test_contradictsubgoal_signal(self) -> None:
        sig = _make_signal("contradictsubgoal", confidence=0.9)
        result = classify_semantic_drift([sig])
        assert result.categories == ["contradictsubgoal"]

    def test_contradictmemory_signal(self) -> None:
        sig = _make_signal("contradictmemory", confidence=0.6)
        result = classify_semantic_drift([sig])
        assert result.categories == ["contradictmemory"]

    def test_contradictprior_behaviour_signal(self) -> None:
        sig = _make_signal("contradictprior_behaviour", confidence=0.7)
        result = classify_semantic_drift([sig])
        assert result.categories == ["contradictprior_behaviour"]

    # ── multiple signals → sorted categories ───────────────────────────

    def test_multiple_signals_sorted_categories(self) -> None:
        signals = [
            _make_signal("contradictsubgoal", confidence=0.9),
            _make_signal("contradictplan", confidence=0.8),
            _make_signal("contradictmemory", confidence=0.6),
        ]
        result = classify_semantic_drift(signals)
        assert result.categories == [
            "contradictmemory",
            "contradictplan",
            "contradictsubgoal",
        ]

    def test_duplicate_categories_deduplicated(self) -> None:
        """Two signals of same type → only one category entry."""
        signals = [
            _make_signal("contradictplan", confidence=0.8),
            _make_signal("contradictplan", confidence=0.9),
        ]
        result = classify_semantic_drift(signals)
        assert result.categories == ["contradictplan"]

    # ── confidence scoring ─────────────────────────────────────────────

    def test_confidence_uses_max_signal(self) -> None:
        """base_confidence = max(signal confidence), not average."""
        signals = [
            _make_signal("contradictmemory", confidence=0.6),
            _make_signal("contradictsubgoal", confidence=0.9),
        ]
        result = classify_semantic_drift(signals)
        # base = 0.9, streak = 1, bonus = 0.1 → 1.0
        assert math.isclose(result.confidence, 1.0)

    def test_confidence_only_contradictplan(self) -> None:
        """Single contradictplan: base=0.7, streak=1, bonus=0.1 → 0.8."""
        result = classify_semantic_drift(
            [_make_signal("contradictplan", confidence=0.7)]
        )
        assert math.isclose(result.confidence, 0.8)

    def test_confidence_only_contradictmemory(self) -> None:
        """Single contradictmemory: base=0.6, streak=1, bonus=0.1 → 0.7."""
        result = classify_semantic_drift(
            [_make_signal("contradictmemory", confidence=0.6)]
        )
        assert math.isclose(result.confidence, 0.7)

    def test_confidence_capped_at_1_0(self) -> None:
        """Even with high base + streak, confidence never exceeds 1.0."""
        signals = [_make_signal("contradictsubgoal", confidence=0.9)]
        prev = SemanticDriftClassification(
            status="semantic_drift",
            categories=["contradictsubgoal"],
            confidence=0.9,
            reasons=[],
            streak=10,
        )
        result = classify_semantic_drift(signals, prev)
        assert result.confidence == 1.0  # min(1.0, 0.9 + 1.1) = 1.0

    # ── streak logic ───────────────────────────────────────────────────

    def test_streak_first_cycle_is_1(self) -> None:
        """When previous is None, streak starts at 1."""
        result = classify_semantic_drift(
            [_make_signal("contradictplan", confidence=0.8)]
        )
        assert result.streak == 1

    def test_streak_increments_on_same_status(self) -> None:
        """Matching status from previous → streak increments."""
        prev = SemanticDriftClassification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.9,
            reasons=[],
            streak=3,
        )
        result = classify_semantic_drift(
            [_make_signal("contradictplan", confidence=0.8)],
            prev,
        )
        assert result.streak == 4

    def test_streak_resets_on_different_status(self) -> None:
        """Status changed → streak resets to 1."""
        prev = SemanticDriftClassification(
            status="no_drift",
            categories=[],
            confidence=0.0,
            reasons=[],
            streak=5,
        )
        result = classify_semantic_drift(
            [_make_signal("contradictsubgoal", confidence=0.9)],
            prev,
        )
        assert result.streak == 1

    def test_streak_does_not_affect_confidence_when_0(self) -> None:
        """no_drift classification has streak=0."""
        result = classify_semantic_drift([])
        assert result.streak == 0
        assert result.confidence == 0.0

    # ── determinism ────────────────────────────────────────────────────

    def test_deterministic_output(self) -> None:
        """Same input always produces the same output."""
        signals = [
            _make_signal("contradictsubgoal", confidence=0.9),
            _make_signal("contradictplan", confidence=0.8),
        ]
        prev = SemanticDriftClassification(
            status="semantic_drift",
            categories=["contradictplan", "contradictsubgoal"],
            confidence=0.95,
            reasons=[],
            streak=2,
        )
        r1 = classify_semantic_drift(signals, prev)
        r2 = classify_semantic_drift(signals, prev)
        assert r1.status == r2.status
        assert r1.categories == r2.categories
        assert r1.confidence == r2.confidence
        assert r1.streak == r2.streak

    def test_deterministic_category_order(self) -> None:
        """Categories are always sorted, regardless of signal order."""
        signals_a = [
            _make_signal("contradictsubgoal", confidence=0.9),
            _make_signal("contradictplan", confidence=0.8),
        ]
        signals_b = [
            _make_signal("contradictplan", confidence=0.8),
            _make_signal("contradictsubgoal", confidence=0.9),
        ]
        r1 = classify_semantic_drift(signals_a)
        r2 = classify_semantic_drift(signals_b)
        assert r1.categories == r2.categories

    # ── non-mutation invariants ────────────────────────────────────────

    def test_does_not_mutate_signals_list(self) -> None:
        """Signals list is not modified by the classifier."""
        signals = [
            _make_signal("contradictmemory", confidence=0.6),
            _make_signal("contradictplan", confidence=0.8),
        ]
        original = list(signals)
        classify_semantic_drift(signals)
        assert signals == original

    def test_does_not_mutate_previous_classification(self) -> None:
        """Previous classification is not modified."""
        prev = SemanticDriftClassification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.8,
            reasons=[],
            streak=4,
        )
        classify_semantic_drift(
            [_make_signal("contradictplan", confidence=0.8)], prev
        )
        assert prev.streak == 4
        assert prev.status == "semantic_drift"

    # ── JSON safety ────────────────────────────────────────────────────

    def test_result_is_json_safe(self) -> None:
        """Classification can be serialized to JSON."""
        import json

        result = classify_semantic_drift(
            [_make_signal("contradictplan", confidence=0.8)]
        )
        dumped = json.dumps({
            "status": result.status,
            "categories": result.categories,
            "confidence": result.confidence,
            "streak": result.streak,
        })
        assert isinstance(dumped, str)

    # ── confidence precision ───────────────────────────────────────────

    def test_confidence_no_floating_point_noise(self) -> None:
        """Confidence values are clean (no 0.30000000000000004 etc.)."""
        prev = SemanticDriftClassification(
            status="semantic_drift",
            categories=["contradictmemory"],
            confidence=0.7,
            reasons=[],
            streak=3,
        )
        result = classify_semantic_drift(
            [_make_signal("contradictmemory", confidence=0.6)],
            prev,
        )
        # base=0.6, streak=4, bonus=0.4 → 1.0
        assert result.confidence == 1.0
