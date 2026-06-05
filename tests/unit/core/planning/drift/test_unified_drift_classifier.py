"""
Tests for Phase 2.9.2 — Unified Drift Classifier
================================================

Covers ``classify_unified_drift()`` with the following test cases:

- Empty signals → no_drift
- Minor drift classification (max weight < 0.4)
- Major drift classification (0.4 ≤ max weight < 0.75)
- Catastrophic drift classification (max weight ≥ 0.75)
- Confidence scoring correct (base × decay_avg + streak_bonus)
- Streak increments correctly
- Streak resets on status change
- Deterministic output
- JSON‑safe
"""
from __future__ import annotations

import json
import math

import pytest

from src.core.planning.drift.unified_drift_classifier import classify_unified_drift
from src.core.planning.drift.unified_drift_types import (
    UnifiedDriftClassification,
    UnifiedDriftSignal,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_signal(
    source: str = "structural",
    type_: str = "shape_mismatch",
    weight: float = 0.5,
    decay: float = 1.0,
    confidence: float = 0.5,
) -> UnifiedDriftSignal:
    return UnifiedDriftSignal(
        source=source,
        type=type_,
        weight=weight,
        decay=decay,
        confidence=confidence,
        details={"test": True},
    )


# ── No drift ──────────────────────────────────────────────────────────────────


class TestNoDrift:
    """Empty signals must produce a no_drift classification."""

    def test_empty_signals_no_drift(self) -> None:
        result = classify_unified_drift([])
        assert result.status == "no_drift"
        assert result.severity == "minor"
        assert result.categories == []
        assert result.confidence == 0.0
        assert result.reasons == []
        assert result.streak == 0

    def test_empty_with_previous_is_none(self) -> None:
        result = classify_unified_drift([], None)
        assert result.status == "no_drift"


# ── Severity ──────────────────────────────────────────────────────────────────


class TestSeverity:
    """Severity must be derived from max signal weight."""

    def test_minor_drift(self) -> None:
        signals = [_make_signal(weight=0.35)]
        result = classify_unified_drift(signals)
        assert result.status == "drift_detected"
        assert result.severity == "minor"

    def test_major_drift_lower_bound(self) -> None:
        signals = [_make_signal(weight=0.40)]
        result = classify_unified_drift(signals)
        assert result.severity == "major"

    def test_major_drift_upper_bound(self) -> None:
        signals = [_make_signal(weight=0.74)]
        result = classify_unified_drift(signals)
        assert result.severity == "major"

    def test_catastrophic_drift(self) -> None:
        signals = [_make_signal(weight=0.75)]
        result = classify_unified_drift(signals)
        assert result.severity == "catastrophic"

    def test_catastrophic_high(self) -> None:
        signals = [_make_signal(weight=0.95)]
        result = classify_unified_drift(signals)
        assert result.severity == "catastrophic"


# ── Categories ────────────────────────────────────────────────────────────────


class TestCategories:
    """Categories must be sorted unique signal types."""

    def test_single_category(self) -> None:
        signals = [_make_signal(type_="shape_mismatch")]
        result = classify_unified_drift(signals)
        assert result.categories == ["shape_mismatch"]

    def test_multiple_sorted_unique(self) -> None:
        signals = [
            _make_signal(source="temporal", type_="oscillation"),
            _make_signal(source="structural", type_="shape_mismatch"),
            _make_signal(source="temporal", type_="oscillation"),  # duplicate
            _make_signal(source="semantic", type_="contradictplan"),
        ]
        result = classify_unified_drift(signals)
        assert result.categories == ["contradictplan", "oscillation", "shape_mismatch"]


# ── Confidence ────────────────────────────────────────────────────────────────


class TestConfidence:
    """Confidence must be min(1.0, base × decay_avg + 0.1 × streak)."""

    def test_base_confidence_no_streak(self) -> None:
        signals = [_make_signal(weight=0.5, decay=1.0)]
        result = classify_unified_drift(signals)
        # base=0.5, decay_avg=1.0, streak=1 → 0.5 * 1.0 + 0.1 = 0.6
        assert result.confidence == pytest.approx(0.6)

    def test_confidence_with_decay_penalty(self) -> None:
        signals = [_make_signal(weight=0.8, decay=0.5)]
        result = classify_unified_drift(signals)
        # base=0.8, decay_avg=0.5, streak=1 → 0.8 * 0.5 + 0.1 = 0.5
        assert result.confidence == pytest.approx(0.5)

    def test_confidence_multi_signal(self) -> None:
        signals = [
            _make_signal(weight=0.6, decay=1.0),
            _make_signal(weight=0.4, decay=0.5),
        ]
        result = classify_unified_drift(signals)
        # base=0.6 (max), decay_avg=0.75, streak=1 → 0.6 * 0.75 + 0.1 = 0.55
        assert result.confidence == pytest.approx(0.55)

    def test_confidence_capped_at_one(self) -> None:
        signals = [_make_signal(weight=1.0, decay=1.0)]
        # Apply streak via previous to get high confidence
        prev = UnifiedDriftClassification(
            status="drift_detected",
            severity="minor",
            categories=["x"],
            confidence=0.9,
            reasons=list(signals),
            streak=5,
        )
        result = classify_unified_drift(signals, prev)
        # base=1.0, decay_avg=1.0, streak=6 → 1.0 * 1.0 + 0.6 = 1.6 → capped 1.0
        assert result.confidence <= 1.0


# ── Streak ────────────────────────────────────────────────────────────────────


class TestStreak:
    """Multi‑cycle streak must increment on status match, reset on change."""

    def test_streak_starts_at_one(self) -> None:
        signals = [_make_signal()]
        result = classify_unified_drift(signals)
        assert result.streak == 1

    def test_streak_increments_on_status_match(self) -> None:
        signals = [_make_signal()]
        prev = UnifiedDriftClassification(
            status="drift_detected",
            severity="minor",
            categories=["shape_mismatch"],
            confidence=0.5,
            reasons=list(signals),
            streak=2,
        )
        result = classify_unified_drift(signals, prev)
        assert result.streak == 3

    def test_streak_resets_on_status_change(self) -> None:
        signals = [_make_signal()]
        prev = UnifiedDriftClassification(
            status="no_drift",
            severity="minor",
            categories=[],
            confidence=0.0,
            reasons=[],
            streak=3,
        )
        result = classify_unified_drift(signals, prev)
        assert result.streak == 1

    def test_streak_zero_for_no_drift(self) -> None:
        result = classify_unified_drift([])
        assert result.streak == 0


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    """Identical inputs must produce identical outputs."""

    def test_deterministic_output(self) -> None:
        signals = [
            _make_signal(source="structural", type_="a"),
            _make_signal(source="temporal", type_="b"),
        ]
        a = classify_unified_drift(signals)
        b = classify_unified_drift(signals)
        assert a == b


# ── JSON safety ───────────────────────────────────────────────────────────────


class TestJSONSafety:
    """UnifiedDriftClassification must be JSON‑serialisable."""

    def test_serialisable(self) -> None:
        signals = [_make_signal()]
        result = classify_unified_drift(signals)
        as_dict = {
            "status": result.status,
            "severity": result.severity,
            "categories": result.categories,
            "confidence": result.confidence,
            "streak": result.streak,
        }
        serialised = json.dumps(as_dict)
        deserialised = json.loads(serialised)
        assert deserialised["status"] == "drift_detected"
        assert deserialised["severity"] == "major"
        assert deserialised["confidence"] == pytest.approx(0.6)


# ── No mutation ───────────────────────────────────────────────────────────────


class TestNoMutation:
    """classify_unified_drift must not mutate its inputs."""

    def test_signals_not_mutated(self) -> None:
        signals = [_make_signal(weight=0.7)]
        original_weight = signals[0].weight
        classify_unified_drift(signals)
        assert signals[0].weight == original_weight

    def test_previous_not_mutated(self) -> None:
        signals = [_make_signal()]
        prev = UnifiedDriftClassification(
            status="drift_detected",
            severity="minor",
            categories=["x"],
            confidence=0.5,
            reasons=list(signals),
            streak=2,
        )
        original_streak = prev.streak
        classify_unified_drift(signals, prev)
        assert prev.streak == original_streak
