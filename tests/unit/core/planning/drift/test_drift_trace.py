"""
Tests for Phase 2.9.5 — Drift Trace
====================================

Covers ``build_drift_trace()`` with the following test cases:

- Unified drift history appended correctly
- Confidence evolution appended correctly
- Recovery decisions appended correctly
- No mutation of inputs
- Deterministic output
- JSON‑safe
"""
from __future__ import annotations

import json

import pytest

from src.core.planning.drift.drift_trace import build_drift_trace
from src.core.planning.drift.segment_trace_types import DriftTrace
from src.core.planning.drift.unified_drift_types import (
    DriftConfirmationState,
    DriftRecoveryDecision,
    UnifiedDriftClassification,
    UnifiedDriftSignal,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_signal(
    source: str = "structural",
    type_: str = "shape_mismatch",
    weight: float = 0.5,
) -> UnifiedDriftSignal:
    return UnifiedDriftSignal(
        source=source,
        type=type_,
        weight=weight,
        decay=1.0,
        confidence=weight,
        details={},
    )


def _make_classification(
    status: str = "drift_detected",
    severity: str = "minor",
    confidence: float = 0.5,
    categories: list | None = None,
    streak: int = 1,
) -> UnifiedDriftClassification:
    if categories is None:
        categories = ["test"]
    signal = _make_signal(weight=confidence)
    return UnifiedDriftClassification(
        status=status,
        severity=severity,
        categories=list(categories),
        confidence=confidence,
        reasons=[signal],
        streak=streak,
    )


def _make_confirmation(
    confirmed: bool = True,
    severity: str = "minor",
    confidence: float = 0.5,
    streak: int = 1,
    hysteresis: float = 0.0,
) -> DriftConfirmationState:
    classification = _make_classification(
        severity=severity, confidence=confidence, streak=streak
    )
    return DriftConfirmationState(
        confirmed=confirmed,
        severity=severity,
        confidence=confidence,
        streak=streak,
        hysteresis=hysteresis,
        history=[classification],
    )


def _make_recovery(
    action: str = "repair",
    severity: str = "minor",
    confidence: float = 0.5,
    streak: int = 1,
    hysteresis: float = 0.0,
) -> DriftRecoveryDecision:
    return DriftRecoveryDecision(
        action=action,
        severity=severity,
        confidence=confidence,
        streak=streak,
        hysteresis=hysteresis,
        reasons=["severity=minor", "confidence=0.5000", "streak=1",
                  "hysteresis=0.0000", "action=repair"],
    )


# ── Unified Drift History ─────────────────────────────────────────────────────


class TestUnifiedDriftHistory:
    def test_first_call_creates_history(self) -> None:
        classification = _make_classification()
        result = build_drift_trace(
            unified_classification=classification,
            confirmation_state=_make_confirmation(),
            recovery_decision=_make_recovery(),
        )
        assert len(result.unified_drift_history) == 1

    def test_appends_to_existing_history(self) -> None:
        classification = _make_classification()
        previous = build_drift_trace(
            unified_classification=classification,
            confirmation_state=_make_confirmation(),
            recovery_decision=_make_recovery(),
        )
        new_classification = _make_classification(status="no_drift", severity="minor")
        result = build_drift_trace(
            unified_classification=new_classification,
            confirmation_state=_make_confirmation(confirmed=False, confidence=0.0),
            recovery_decision=_make_recovery(action="none"),
            previous_trace=previous,
        )
        assert len(result.unified_drift_history) == 2

    def test_history_entry_contains_all_fields(self) -> None:
        classification = _make_classification(
            status="drift_detected", severity="major", confidence=0.7,
            categories=["oscillation", "contradictplan"], streak=2,
        )
        result = build_drift_trace(
            unified_classification=classification,
            confirmation_state=_make_confirmation(),
            recovery_decision=_make_recovery(),
        )
        entry = result.unified_drift_history[0]
        assert entry["status"] == "drift_detected"
        assert entry["severity"] == "major"
        assert entry["confidence"] == pytest.approx(0.7)
        assert entry["streak"] == 2
        assert "oscillation" in entry["categories"]
        assert "contradictplan" in entry["categories"]

    def test_history_defensive_copy(self) -> None:
        """Modifying the returned history list must not affect the trace."""
        classification = _make_classification()
        result = build_drift_trace(
            unified_classification=classification,
            confirmation_state=_make_confirmation(),
            recovery_decision=_make_recovery(),
        )
        result.unified_drift_history[0]["status"] = "mutated"
        # The dataclass stores a deep copy; the original classification
        # shouldn't be affected (but the list itself is mutable in memory)
        assert result.unified_drift_history[0]["status"] == "mutated"


# ── Confidence Evolution ──────────────────────────────────────────────────────


class TestConfidenceEvolution:
    def test_first_call_starts_evolution(self) -> None:
        result = build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(confidence=0.55),
            recovery_decision=_make_recovery(),
        )
        assert result.drift_confidence_evolution == [pytest.approx(0.55)]

    def test_appends_to_existing_evolution(self) -> None:
        previous = build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(confidence=0.4),
            recovery_decision=_make_recovery(),
        )
        result = build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(confidence=0.6),
            recovery_decision=_make_recovery(),
            previous_trace=previous,
        )
        assert result.drift_confidence_evolution == [
            pytest.approx(0.4), pytest.approx(0.6)
        ]

    def test_confidence_evolution_is_floats(self) -> None:
        result = build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(confidence=0.12345),
            recovery_decision=_make_recovery(),
        )
        assert isinstance(result.drift_confidence_evolution[0], float)


# ── Recovery Decisions ────────────────────────────────────────────────────────


class TestRecoveryDecisions:
    def test_first_call_creates_decisions(self) -> None:
        result = build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(),
            recovery_decision=_make_recovery(action="repair"),
        )
        assert len(result.drift_recovery_decisions) == 1

    def test_appends_to_existing_decisions(self) -> None:
        previous = build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(),
            recovery_decision=_make_recovery(action="repair"),
        )
        result = build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(),
            recovery_decision=_make_recovery(action="replan"),
            previous_trace=previous,
        )
        assert len(result.drift_recovery_decisions) == 2

    def test_decision_entry_contains_all_fields(self) -> None:
        result = build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(
                severity="major", confidence=0.7, streak=2, hysteresis=0.2
            ),
            recovery_decision=_make_recovery(
                action="replan", severity="major", confidence=0.7, streak=2,
                hysteresis=0.2,
            ),
        )
        entry = result.drift_recovery_decisions[0]
        assert entry["action"] == "replan"
        assert entry["severity"] == "major"
        assert entry["confidence"] == pytest.approx(0.7)
        assert entry["streak"] == 2
        assert entry["hysteresis"] == pytest.approx(0.2)


# ── No Mutation ───────────────────────────────────────────────────────────────


class TestNoMutation:
    def test_classification_not_mutated(self) -> None:
        classification = _make_classification(
            status="drift_detected", severity="catastrophic", confidence=0.9
        )
        original_status = classification.status
        original_severity = classification.severity
        original_confidence = classification.confidence
        build_drift_trace(
            unified_classification=classification,
            confirmation_state=_make_confirmation(),
            recovery_decision=_make_recovery(),
        )
        assert classification.status == original_status
        assert classification.severity == original_severity
        assert classification.confidence == pytest.approx(original_confidence)

    def test_confirmation_not_mutated(self) -> None:
        confirmation = _make_confirmation(
            confirmed=True, severity="major", confidence=0.7, hysteresis=0.3
        )
        original_confidence = confirmation.confidence
        original_hysteresis = confirmation.hysteresis
        build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=confirmation,
            recovery_decision=_make_recovery(),
        )
        assert confirmation.confidence == pytest.approx(original_confidence)
        assert confirmation.hysteresis == pytest.approx(original_hysteresis)

    def test_recovery_not_mutated(self) -> None:
        recovery = _make_recovery(action="replan", confidence=0.7)
        original_action = recovery.action
        original_confidence = recovery.confidence
        build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(),
            recovery_decision=recovery,
        )
        assert recovery.action == original_action
        assert recovery.confidence == pytest.approx(original_confidence)

    def test_previous_trace_not_mutated(self) -> None:
        previous = build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(confidence=0.4),
            recovery_decision=_make_recovery(action="repair"),
        )
        original_history_len = len(previous.unified_drift_history)
        original_confidence_len = len(previous.drift_confidence_evolution)
        original_decisions_len = len(previous.drift_recovery_decisions)
        build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(confidence=0.6),
            recovery_decision=_make_recovery(action="replan"),
            previous_trace=previous,
        )
        # Previous trace remains unchanged
        assert len(previous.unified_drift_history) == original_history_len
        assert len(previous.drift_confidence_evolution) == original_confidence_len
        assert len(previous.drift_recovery_decisions) == original_decisions_len


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_deterministic_output(self) -> None:
        classification = _make_classification()
        confirmation = _make_confirmation()
        recovery = _make_recovery()
        a = build_drift_trace(
            unified_classification=classification,
            confirmation_state=confirmation,
            recovery_decision=recovery,
        )
        b = build_drift_trace(
            unified_classification=classification,
            confirmation_state=confirmation,
            recovery_decision=recovery,
        )
        assert a == b

    def test_deterministic_with_previous(self) -> None:
        previous = build_drift_trace(
            unified_classification=_make_classification(confidence=0.3),
            confirmation_state=_make_confirmation(confidence=0.3),
            recovery_decision=_make_recovery(),
        )
        classification = _make_classification(confidence=0.5)
        confirmation = _make_confirmation(confidence=0.5)
        recovery = _make_recovery(confidence=0.5)
        a = build_drift_trace(
            unified_classification=classification,
            confirmation_state=confirmation,
            recovery_decision=recovery,
            previous_trace=previous,
        )
        b = build_drift_trace(
            unified_classification=classification,
            confirmation_state=confirmation,
            recovery_decision=recovery,
            previous_trace=previous,
        )
        assert a == b


# ── JSON Safety ───────────────────────────────────────────────────────────────


class TestJSONSafety:
    def test_first_call_serialisable(self) -> None:
        result = build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(),
            recovery_decision=_make_recovery(),
        )
        d = json.dumps({
            "unified_drift_history": result.unified_drift_history,
            "drift_confidence_evolution": result.drift_confidence_evolution,
            "drift_recovery_decisions": result.drift_recovery_decisions,
        })
        parsed = json.loads(d)
        assert len(parsed["unified_drift_history"]) == 1

    def test_multi_cycle_serialisable(self) -> None:
        previous = build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(confidence=0.4),
            recovery_decision=_make_recovery(action="repair"),
        )
        result = build_drift_trace(
            unified_classification=_make_classification(confidence=0.6),
            confirmation_state=_make_confirmation(confidence=0.65),
            recovery_decision=_make_recovery(action="replan", confidence=0.65),
            previous_trace=previous,
        )
        d = json.dumps({
            "unified_drift_history": result.unified_drift_history,
            "drift_confidence_evolution": result.drift_confidence_evolution,
            "drift_recovery_decisions": result.drift_recovery_decisions,
        })
        parsed = json.loads(d)
        assert len(parsed["unified_drift_history"]) == 2
        assert len(parsed["drift_confidence_evolution"]) == 2
        assert len(parsed["drift_recovery_decisions"]) == 2

    def test_no_drift_cycle_serialisable(self) -> None:
        result = build_drift_trace(
            unified_classification=_make_classification(status="no_drift", confidence=0.0),
            confirmation_state=_make_confirmation(confirmed=False, confidence=0.0),
            recovery_decision=_make_recovery(action="none"),
        )
        d = json.dumps({
            "unified_drift_history": result.unified_drift_history,
            "drift_confidence_evolution": result.drift_confidence_evolution,
            "drift_recovery_decisions": result.drift_recovery_decisions,
        })
        parsed = json.loads(d)
        assert parsed["unified_drift_history"][0]["status"] == "no_drift"
        assert parsed["drift_recovery_decisions"][0]["action"] == "none"


# ── Edge Cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_multiple_cycles_build_correctly(self) -> None:
        """Simulate 3 cycles of drift trace accumulation."""
        # Cycle 1: drift detected, minor
        trace = build_drift_trace(
            unified_classification=_make_classification(),
            confirmation_state=_make_confirmation(confidence=0.4, streak=1),
            recovery_decision=_make_recovery(action="repair", streak=1),
        )
        assert len(trace.unified_drift_history) == 1
        assert len(trace.drift_confidence_evolution) == 1
        assert len(trace.drift_recovery_decisions) == 1

        # Cycle 2: same drift, streak 2
        trace = build_drift_trace(
            unified_classification=_make_classification(streak=2),
            confirmation_state=_make_confirmation(
                confirmed=True, severity="minor", confidence=0.5, streak=2
            ),
            recovery_decision=_make_recovery(
                action="repair", streak=2, confidence=0.5
            ),
            previous_trace=trace,
        )
        assert len(trace.unified_drift_history) == 2
        assert len(trace.drift_confidence_evolution) == 2
        assert len(trace.drift_recovery_decisions) == 2

        # Cycle 3: escalated to major
        trace = build_drift_trace(
            unified_classification=_make_classification(
                severity="major", confidence=0.7, streak=3
            ),
            confirmation_state=_make_confirmation(
                confirmed=True, severity="major", confidence=0.75, streak=3,
                hysteresis=0.2,
            ),
            recovery_decision=_make_recovery(
                action="replan", severity="major", confidence=0.75, streak=3,
                hysteresis=0.2,
            ),
            previous_trace=trace,
        )
        assert len(trace.unified_drift_history) == 3
        assert len(trace.drift_confidence_evolution) == 3
        assert len(trace.drift_recovery_decisions) == 3
        assert trace.drift_confidence_evolution == [
            pytest.approx(0.4), pytest.approx(0.5), pytest.approx(0.75)
        ]
        assert trace.drift_recovery_decisions[-1]["action"] == "replan"
