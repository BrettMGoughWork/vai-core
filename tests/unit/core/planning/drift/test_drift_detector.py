"""
Behaviour tests for 2.3.8 Drift Detection.

Design principles:
- Fakes over mocks: GovernedSignal is a pure dataclass, used directly.
- Behaviour focus: test outcomes, not internal implementation.
- Exhaustive threshold boundary coverage.
- Determinism: same inputs always produce same outputs.
"""
from __future__ import annotations

import pytest

from src.core.signals.model import (
    GovernedSignal,
    SignalSeverity,
    SignalSource,
    SignalType,
)
from src.core.planning.drift.drift_types import (
    DriftRecoveryAction,
    DriftReport,
    StepContext,
)
from src.core.planning.drift.drift_detector import DriftDetector


# ---------------------------------------------------------------------------
# Fake signal builders
# ---------------------------------------------------------------------------

def make_drift_signal(
    source: str = SignalSource.PLANNING_DEVIATION,
    confidence: float = 0.8,
    timestamp: int = 1_000_000,
    severity: SignalSeverity = SignalSeverity.WARN,
) -> GovernedSignal:
    return GovernedSignal(
        signal_type=SignalType.DRIFT,
        severity=severity,
        confidence=confidence,
        source=source,
        payload={},
        timestamp=timestamp,
    )


def make_non_drift_signal(source: str = "runtime") -> GovernedSignal:
    return GovernedSignal(
        signal_type=SignalType.UNSAFE,
        severity=SignalSeverity.CRITICAL,
        confidence=1.0,
        source=source,
        payload={},
        timestamp=1_000_000,
    )


def make_step(
    signals: list[GovernedSignal],
    timestamp: int = 1_000_000,
    step_id: str = "step-001",
) -> StepContext:
    return StepContext(
        step_id=step_id,
        signals=tuple(signals),
        timestamp=timestamp,
    )


@pytest.fixture
def detector() -> DriftDetector:
    return DriftDetector()


# ---------------------------------------------------------------------------
# compute_confidence — unit behaviour
# ---------------------------------------------------------------------------

class TestComputeConfidence:
    def test_empty_signals_returns_zero(self, detector):
        assert detector.compute_confidence([]) == 0.0

    def test_single_signal_returns_its_confidence(self, detector):
        signal = make_drift_signal(source=SignalSource.PLANNING_DEVIATION, confidence=0.8)
        # Weighted avg of one signal = signal.confidence (weight cancels)
        assert detector.compute_confidence([signal]) == pytest.approx(0.8)

    def test_result_is_in_unit_interval(self, detector):
        signals = [make_drift_signal(confidence=c) for c in [0.0, 0.5, 1.0]]
        result = detector.compute_confidence(signals)
        assert 0.0 <= result <= 1.0

    def test_higher_weight_source_dominates(self, detector):
        # COGNITIVE_DISSONANCE (0.9) vs SUBGOAL_STALL (0.6)
        high = make_drift_signal(source=SignalSource.COGNITIVE_DISSONANCE, confidence=1.0)
        low  = make_drift_signal(source=SignalSource.SUBGOAL_STALL, confidence=0.0)
        result = detector.compute_confidence([high, low])
        # Weighted avg biased toward high-weight signal → > 0.5
        assert result > 0.5

    def test_unknown_source_uses_default_weight(self, detector):
        signal = make_drift_signal(source="unknown_source", confidence=0.7)
        # Should not raise; should return a valid float
        result = detector.compute_confidence([signal])
        assert result == pytest.approx(0.7)

    def test_deterministic_same_input_same_output(self, detector):
        signals = [
            make_drift_signal(source=SignalSource.LOOP_ANOMALY, confidence=0.6),
            make_drift_signal(source=SignalSource.EXECUTION_MISMATCH, confidence=0.9),
        ]
        assert detector.compute_confidence(signals) == detector.compute_confidence(signals)

    def test_legacy_source_accepted(self, detector):
        signal = make_drift_signal(source="segments", confidence=0.75)
        result = detector.compute_confidence([signal])
        assert result == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# detect_drift — filtering and aggregation
# ---------------------------------------------------------------------------

class TestDetectDrift:
    def test_empty_signals_returns_zero_confidence(self, detector):
        step = make_step([])
        report = detector.detect_drift(step)
        assert report.confidence == 0.0
        assert report.signal is None

    def test_non_drift_signals_are_ignored(self, detector):
        step = make_step([make_non_drift_signal()])
        report = detector.detect_drift(step)
        assert report.confidence == 0.0

    def test_drift_signals_are_aggregated(self, detector):
        signals = [
            make_drift_signal(source=SignalSource.PLANNING_DEVIATION, confidence=0.8),
            make_drift_signal(source=SignalSource.LOOP_ANOMALY, confidence=0.7),
        ]
        step = make_step(signals)
        report = detector.detect_drift(step)
        assert report.confidence > 0.0
        assert report.signal is not None

    def test_mixed_signal_types_only_drift_counted(self, detector):
        drift   = make_drift_signal(confidence=0.9)
        non_drift = make_non_drift_signal()
        step_drift_only = make_step([drift])
        step_mixed      = make_step([drift, non_drift])
        assert (
            detector.detect_drift(step_drift_only).confidence
            == pytest.approx(detector.detect_drift(step_mixed).confidence)
        )

    def test_stale_signals_reduce_confidence(self, detector):
        anchor = 1_000_000
        fresh_signal = make_drift_signal(confidence=0.9, timestamp=anchor)
        stale_signal = make_drift_signal(confidence=0.9, timestamp=anchor - 60_000)  # 60s ago

        fresh_step = make_step([fresh_signal], timestamp=anchor)
        stale_step = make_step([stale_signal], timestamp=anchor)

        assert detector.detect_drift(fresh_step).confidence > detector.detect_drift(stale_step).confidence

    def test_primary_signal_is_highest_contributor(self, detector):
        low  = make_drift_signal(source=SignalSource.SUBGOAL_STALL,        confidence=0.3)
        high = make_drift_signal(source=SignalSource.COGNITIVE_DISSONANCE,  confidence=0.9)
        step = make_step([low, high])
        report = detector.detect_drift(step)
        assert report.signal is high

    def test_deterministic_ordering(self, detector):
        signals = [
            make_drift_signal(source=SignalSource.PLANNING_DEVIATION, confidence=0.7),
            make_drift_signal(source=SignalSource.EXECUTION_MISMATCH,  confidence=0.8),
            make_drift_signal(source=SignalSource.LOOP_ANOMALY,        confidence=0.5),
        ]
        step = make_step(signals)
        r1 = detector.detect_drift(step)
        r2 = detector.detect_drift(step)
        assert r1 == r2


# ---------------------------------------------------------------------------
# Severity bands
# ---------------------------------------------------------------------------

class TestSeverityBands:
    def _report_for_confidence(self, detector, confidence: float) -> DriftReport:
        # Produce a report with a known confidence by using a fresh signal
        # (recency = 1.0 for fresh signals) so confidence == compute_confidence
        ts = 1_000_000
        signal = GovernedSignal(
            signal_type=SignalType.DRIFT,
            severity=SignalSeverity.WARN,
            confidence=confidence,
            source="subgoals",  # weight 0.6; single signal → result == confidence
            payload={},
            timestamp=ts,
        )
        return detector.detect_drift(make_step([signal], timestamp=ts))

    def test_confidence_below_0_3_is_info(self, detector):
        report = self._report_for_confidence(detector, 0.1)
        assert report.severity == SignalSeverity.INFO

    def test_confidence_at_0_3_is_warn(self, detector):
        report = self._report_for_confidence(detector, 0.3)
        assert report.severity == SignalSeverity.WARN

    def test_confidence_at_0_59_is_warn(self, detector):
        report = self._report_for_confidence(detector, 0.59)
        assert report.severity == SignalSeverity.WARN

    def test_confidence_at_0_6_is_critical(self, detector):
        report = self._report_for_confidence(detector, 0.6)
        assert report.severity == SignalSeverity.CRITICAL


# ---------------------------------------------------------------------------
# Recovery thresholds
# ---------------------------------------------------------------------------

class TestRecoveryThresholds:
    def _action_for_confidence(self, detector, confidence: float) -> DriftRecoveryAction:
        ts = 1_000_000
        signal = GovernedSignal(
            signal_type=SignalType.DRIFT,
            severity=SignalSeverity.WARN,
            confidence=confidence,
            source="subgoals",
            payload={},
            timestamp=ts,
        )
        return detector.detect_drift(make_step([signal], timestamp=ts)).recommended_action

    @pytest.mark.parametrize("confidence,expected", [
        (0.0,  DriftRecoveryAction.NONE),
        (0.29, DriftRecoveryAction.NONE),
        (0.3,  DriftRecoveryAction.RESET_SUBGOAL),
        (0.59, DriftRecoveryAction.RESET_SUBGOAL),
        (0.6,  DriftRecoveryAction.REPLAN),
        (0.84, DriftRecoveryAction.REPLAN),
        (0.85, DriftRecoveryAction.ABORT),
        (1.0,  DriftRecoveryAction.ABORT),
    ])
    def test_threshold_boundary(self, detector, confidence, expected):
        assert self._action_for_confidence(detector, confidence) == expected


# ---------------------------------------------------------------------------
# recover_if_needed
# ---------------------------------------------------------------------------

class TestRecoverIfNeeded:
    def _report(self, confidence: float) -> DriftReport:
        return DriftReport(
            signal=None,
            confidence=confidence,
            severity=SignalSeverity.INFO,
            recommended_action=DriftRecoveryAction.NONE,
        )

    def test_returns_none_below_threshold(self, detector):
        assert detector.recover_if_needed(self._report(0.1)) is None

    def test_returns_none_at_zero(self, detector):
        assert detector.recover_if_needed(self._report(0.0)) is None

    def test_returns_action_at_reset_threshold(self, detector):
        assert detector.recover_if_needed(self._report(0.3)) == DriftRecoveryAction.RESET_SUBGOAL

    def test_returns_replan(self, detector):
        assert detector.recover_if_needed(self._report(0.7)) == DriftRecoveryAction.REPLAN

    def test_returns_abort(self, detector):
        assert detector.recover_if_needed(self._report(0.9)) == DriftRecoveryAction.ABORT
