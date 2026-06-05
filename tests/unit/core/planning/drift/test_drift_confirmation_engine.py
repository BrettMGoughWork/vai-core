"""
Tests for Phase 2.9.3 — Drift Confirmation Engine
==================================================

Covers ``confirm_drift()`` with the following test cases:

- Minor drift requires 2 cycles
- Major drift requires 2 cycles
- Catastrophic drift confirmed immediately (1 cycle)
- Confidence accumulation correct
- Hysteresis suppresses low‑confidence drift
- Hysteresis decays correctly
- Deterministic output
- JSON‑safe
- No mutation of inputs
"""
from __future__ import annotations

import json

import pytest

from src.core.planning.drift.drift_confirmation_engine import confirm_drift
from src.core.planning.drift.unified_drift_types import (
    DriftConfirmationState,
    UnifiedDriftClassification,
    UnifiedDriftSignal,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_signal(weight: float = 0.5) -> UnifiedDriftSignal:
    return UnifiedDriftSignal(
        source="structural",
        type="shape_mismatch",
        weight=weight,
        decay=1.0,
        confidence=weight,
        details={},
    )


def _make_classification(
    status: str = "drift_detected",
    severity: str = "minor",
    confidence: float = 0.5,
    streak: int = 1,
) -> UnifiedDriftClassification:
    if status == "no_drift":
        return UnifiedDriftClassification(
            status="no_drift",
            severity="minor",
            categories=[],
            confidence=0.0,
            reasons=[],
            streak=0,
        )
    return UnifiedDriftClassification(
        status=status,
        severity=severity,
        categories=["test"],
        confidence=confidence,
        reasons=[_make_signal(weight=confidence)],
        streak=streak,
    )


# ── No drift ──────────────────────────────────────────────────────────────────


class TestNoDrift:
    """A no_drift classification must produce unconfirmed state."""

    def test_no_drift_unconfirmed(self) -> None:
        current = _make_classification(status="no_drift")
        result = confirm_drift(current)
        assert result.confirmed is False
        assert result.streak == 0
        assert result.severity == "minor"

    def test_no_drift_resets_streak(self) -> None:
        prev = DriftConfirmationState(
            confirmed=True,
            severity="major",
            confidence=0.8,
            streak=3,
            hysteresis=0.5,
            history=[_make_classification()],
        )
        current = _make_classification(status="no_drift")
        result = confirm_drift(current, prev)
        assert result.streak == 0
        assert result.confirmed is False


# ── Streak thresholds ─────────────────────────────────────────────────────────


class TestStreakThresholds:
    """Confirmation requires minimum streak per severity."""

    def test_minor_requires_two_cycles(self) -> None:
        current = _make_classification(severity="minor")
        result = confirm_drift(current)
        assert result.streak == 1
        assert result.confirmed is False  # need 2

    def test_minor_confirmed_on_second_cycle(self) -> None:
        current = _make_classification(severity="minor")
        prev = DriftConfirmationState(
            confirmed=False,
            severity="minor",
            confidence=0.5,
            streak=1,
            hysteresis=0.0,
            history=[_make_classification(severity="minor")],
        )
        result = confirm_drift(current, prev)
        assert result.streak == 2
        assert result.confirmed is True

    def test_major_requires_two_cycles(self) -> None:
        current = _make_classification(severity="major")
        result = confirm_drift(current)
        assert result.streak == 1
        assert result.confirmed is False

    def test_major_confirmed_on_second_cycle(self) -> None:
        current = _make_classification(severity="major")
        prev = DriftConfirmationState(
            confirmed=False,
            severity="minor",
            confidence=0.6,
            streak=1,
            hysteresis=0.0,
            history=[_make_classification(severity="major")],
        )
        result = confirm_drift(current, prev)
        assert result.streak == 2
        assert result.confirmed is True

    def test_catastrophic_confirmed_immediately(self) -> None:
        current = _make_classification(severity="catastrophic", confidence=0.8)
        result = confirm_drift(current)
        assert result.streak == 1
        assert result.confirmed is True


# ── Confidence accumulation ───────────────────────────────────────────────────


class TestConfidenceAccumulation:
    """Confidence accumulates: current + previous × 0.5, capped at 1.0."""

    def test_no_previous(self) -> None:
        current = _make_classification(confidence=0.6)
        result = confirm_drift(current)
        assert result.confidence == 0.6

    def test_with_previous(self) -> None:
        prev = DriftConfirmationState(
            confirmed=False,
            severity="minor",
            confidence=0.4,
            streak=1,
            hysteresis=0.0,
            history=[],
        )
        current = _make_classification(confidence=0.6)
        result = confirm_drift(current, prev)
        # 0.6 + 0.4 × 0.5 = 0.8
        assert result.confidence == pytest.approx(0.8)

    def test_capped_at_one(self) -> None:
        prev = DriftConfirmationState(
            confirmed=False,
            severity="minor",
            confidence=0.9,
            streak=1,
            hysteresis=0.0,
            history=[],
        )
        current = _make_classification(confidence=0.9)
        result = confirm_drift(current, prev)
        # 0.9 + 0.9 × 0.5 = 1.35 → 1.0
        assert result.confidence == 1.0


# ── Hysteresis ────────────────────────────────────────────────────────────────


class TestHysteresis:
    """Hysteresis prevents rapid flip‑flopping between drift / no‑drift."""

    def test_hysteresis_starts_at_zero(self) -> None:
        current = _make_classification(severity="minor")
        result = confirm_drift(current)
        # Not confirmed yet (streak=1), so no boost → hysteresis = 0.0
        assert result.hysteresis == 0.0

    def test_hysteresis_boosts_when_confirmed(self) -> None:
        current = _make_classification(severity="catastrophic", confidence=0.8)
        result = confirm_drift(current)
        # Confirmed immediately → hysteresis = 0.0 + 0.2 = 0.2
        assert result.hysteresis == pytest.approx(0.2)

    def test_hysteresis_decays_from_previous(self) -> None:
        prev = DriftConfirmationState(
            confirmed=False,
            severity="minor",
            confidence=0.5,
            streak=0,
            hysteresis=0.3,
            history=[],
        )
        current = _make_classification(severity="minor")
        result = confirm_drift(current, prev)
        # Streak becomes 1 (prev.streak=0 + 1), not confirmed for minor
        # → no boost, just decay: 0.3 - 0.1 = 0.2
        assert result.hysteresis == pytest.approx(0.2)

    def test_hysteresis_decays_then_boosts(self) -> None:
        prev = DriftConfirmationState(
            confirmed=True,
            severity="major",
            confidence=0.6,
            streak=1,
            hysteresis=0.3,
            history=[],
        )
        current = _make_classification(severity="major")
        result = confirm_drift(current, prev)
        # Confirmed (streak=2), hysteresis = (0.3-0.1) + 0.2 = 0.4
        assert result.hysteresis == pytest.approx(0.4)

    def test_hysteresis_suppresses_low_confidence(self) -> None:
        prev = DriftConfirmationState(
            confirmed=True,
            severity="catastrophic",
            confidence=0.8,
            streak=2,
            hysteresis=0.6,
            history=[],
        )
        current = _make_classification(
            severity="catastrophic", confidence=0.5
        )
        result = confirm_drift(current, prev)
        # Hysteresis = max(0, 0.6-0.1) + 0.2 = 0.7 (since catastrophic → confirmed immediately)
        # current.confidence (0.5) < 0.7 → suppressed
        assert result.confirmed is False
        assert result.severity == "minor"

    def test_hysteresis_does_not_suppress_high_confidence(self) -> None:
        prev = DriftConfirmationState(
            confirmed=True,
            severity="catastrophic",
            confidence=0.8,
            streak=2,
            hysteresis=0.3,
            history=[],
        )
        current = _make_classification(
            severity="catastrophic", confidence=0.7
        )
        result = confirm_drift(current, prev)
        # Hysteresis = max(0, 0.3-0.1) + 0.2 = 0.4
        # current.confidence (0.7) >= 0.4 → NOT suppressed
        assert result.confirmed is True

    def test_hysteresis_clamped_at_one(self) -> None:
        prev = DriftConfirmationState(
            confirmed=True,
            severity="catastrophic",
            confidence=0.8,
            streak=3,
            hysteresis=0.95,
            history=[],
        )
        current = _make_classification(severity="catastrophic", confidence=0.8)
        result = confirm_drift(current, prev)
        # Hysteresis = max(0, 0.95-0.1) + 0.2 = 1.05 → 1.0
        assert result.hysteresis <= 1.0


# ── Severity propagation ──────────────────────────────────────────────────────


class TestSeverityPropagation:
    """Confirmed → current.severity, else → minor."""

    def test_severity_propagated_when_confirmed(self) -> None:
        current = _make_classification(
            severity="catastrophic", confidence=0.8
        )
        result = confirm_drift(current)
        assert result.confirmed is True
        assert result.severity == "catastrophic"

    def test_severity_falls_back_to_minor(self) -> None:
        current = _make_classification(severity="major")
        result = confirm_drift(current)
        assert result.confirmed is False
        assert result.severity == "minor"


# ── History tracking ──────────────────────────────────────────────────────────


class TestHistory:
    """Current classification must be appended to history."""

    def test_first_call_creates_history(self) -> None:
        current = _make_classification()
        result = confirm_drift(current)
        assert len(result.history) == 1
        assert result.history[0] is current

    def test_appends_to_existing_history(self) -> None:
        prev_cls = _make_classification(severity="minor")
        prev = DriftConfirmationState(
            confirmed=False,
            severity="minor",
            confidence=0.5,
            streak=1,
            hysteresis=0.0,
            history=[prev_cls],
        )
        current = _make_classification(severity="major")
        result = confirm_drift(current, prev)
        assert len(result.history) == 2
        assert result.history[0] is prev_cls
        assert result.history[1] is current

    def test_history_defensive_copy(self) -> None:
        """History list is independent of the input list passed at construction."""
        previous_list: list[UnifiedDriftClassification] = []
        current = _make_classification()
        prev = DriftConfirmationState(
            confirmed=False,
            severity="minor",
            confidence=0.5,
            streak=0,
            hysteresis=0.0,
            history=previous_list,
        )
        # Mutating the original list must not affect prev.history
        previous_list.append(_make_classification())
        assert len(prev.history) == 0
        # confirm_drift appends to a copy, not the original
        result = confirm_drift(current, prev)
        assert len(result.history) == 1


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    """Identical inputs must produce identical outputs."""

    def test_deterministic_output(self) -> None:
        current = _make_classification(severity="minor")
        prev = DriftConfirmationState(
            confirmed=False,
            severity="minor",
            confidence=0.5,
            streak=1,
            hysteresis=0.0,
            history=[],
        )
        a = confirm_drift(current, prev)
        b = confirm_drift(current, prev)
        assert a == b


# ── JSON safety ───────────────────────────────────────────────────────────────


class TestJSONSafety:
    """DriftConfirmationState must be JSON‑serialisable."""

    def test_serialisable(self) -> None:
        current = _make_classification(severity="catastrophic", confidence=0.8)
        result = confirm_drift(current)
        as_dict = {
            "confirmed": result.confirmed,
            "severity": result.severity,
            "confidence": result.confidence,
            "streak": result.streak,
            "hysteresis": result.hysteresis,
        }
        serialised = json.dumps(as_dict)
        deserialised = json.loads(serialised)
        assert deserialised["confirmed"] is True
        assert deserialised["severity"] == "catastrophic"


# ── No mutation ───────────────────────────────────────────────────────────────


class TestNoMutation:
    """confirm_drift must not mutate its inputs."""

    def test_current_not_mutated(self) -> None:
        current = _make_classification()
        original = current.confidence
        confirm_drift(current)
        assert current.confidence == original

    def test_previous_not_mutated(self) -> None:
        prev = DriftConfirmationState(
            confirmed=True,
            severity="major",
            confidence=0.7,
            streak=2,
            hysteresis=0.4,
            history=[_make_classification()],
        )
        original_hysteresis = prev.hysteresis
        original_streak = prev.streak
        original_history_len = len(prev.history)
        current = _make_classification(severity="major")
        confirm_drift(current, prev)
        assert prev.hysteresis == original_hysteresis
        assert prev.streak == original_streak
        assert len(prev.history) == original_history_len
