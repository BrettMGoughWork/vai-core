from __future__ import annotations

from typing import List, Optional

from src.core.signals.model import (
    GovernedSignal,
    SignalSeverity,
    SignalType,
    SIGNAL_WEIGHTS,
    DEFAULT_SIGNAL_WEIGHT,
)
from src.core.planning.drift.drift_types import (
    DriftRecoveryAction,
    DriftReport,
    StepContext,
)


class DriftDetector:
    """
    Pure, deterministic drift detection engine.

    Uses only the governed-signal framework and the transition table from
    SIGNAL_WEIGHTS. No state, no side effects, no heuristics, no LLM calls.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_drift(self, step: StepContext) -> DriftReport:
        """
        Aggregate drift signals from step.signals and produce a DriftReport.

        Only DRIFT-type signals are considered. Recency is computed relative
        to step.timestamp so that stale signals contribute less.
        """
        drift_signals = [
            s for s in step.signals if s.signal_type == SignalType.DRIFT
        ]

        confidence = self.compute_confidence(drift_signals)
        recency    = self._recency_factor(drift_signals, step.timestamp)
        effective_confidence = min(1.0, confidence * recency)

        severity  = self._severity_from_confidence(effective_confidence)
        action    = self._action_from_confidence(effective_confidence)
        primary   = self._primary_signal(drift_signals, step.timestamp)

        return DriftReport(
            signal=primary,
            confidence=effective_confidence,
            severity=severity,
            recommended_action=action,
        )

    def compute_confidence(self, signals: List[GovernedSignal]) -> float:
        """
        Compute a normalised weighted-average confidence score in [0.0, 1.0].

        Weights are sourced from SIGNAL_WEIGHTS. Unknown sources use
        DEFAULT_SIGNAL_WEIGHT. Returns 0.0 for an empty signal list.
        """
        if not signals:
            return 0.0

        total_weight     = 0.0
        weighted_sum     = 0.0

        for signal in signals:
            w = SIGNAL_WEIGHTS.get(signal.source, DEFAULT_SIGNAL_WEIGHT)
            weighted_sum += w * signal.confidence
            total_weight += w

        if total_weight == 0.0:
            return 0.0

        return min(1.0, weighted_sum / total_weight)

    def recover_if_needed(self, report: DriftReport) -> Optional[DriftRecoveryAction]:
        """
        Return the recovery action implied by report.confidence, or None if no
        action is needed (confidence < 0.3).
        """
        action = self._action_from_confidence(report.confidence)
        return None if action is DriftRecoveryAction.NONE else action

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _recency_factor(
        self,
        signals: List[GovernedSignal],
        anchor_ts: int,
    ) -> float:
        """
        Average per-signal recency decay relative to anchor_ts.

        decay_i = 1 / (1 + age_seconds_i)

        Returns 1.0 when there are no signals (no penalty).
        """
        if not signals:
            return 1.0

        total = 0.0
        for s in signals:
            age_ms = max(0, anchor_ts - s.timestamp)
            total += 1.0 / (1.0 + age_ms / 1000.0)

        return total / len(signals)

    def _primary_signal(
        self,
        signals: List[GovernedSignal],
        anchor_ts: int,
    ) -> Optional[GovernedSignal]:
        """
        Return the signal with the highest contribution (weight × recency × confidence).
        Tie-break: newest timestamp, then source name (alphabetical).
        """
        if not signals:
            return None

        def score(s: GovernedSignal) -> tuple:
            w = SIGNAL_WEIGHTS.get(s.source, DEFAULT_SIGNAL_WEIGHT)
            age_ms = max(0, anchor_ts - s.timestamp)
            recency = 1.0 / (1.0 + age_ms / 1000.0)
            contribution = w * recency * s.confidence
            return (contribution, s.timestamp, s.source)

        return max(signals, key=score)

    def _severity_from_confidence(self, confidence: float) -> SignalSeverity:
        if confidence >= 0.6:
            return SignalSeverity.CRITICAL
        if confidence >= 0.3:
            return SignalSeverity.WARN
        return SignalSeverity.INFO

    def _action_from_confidence(self, confidence: float) -> DriftRecoveryAction:
        if confidence >= 0.85:
            return DriftRecoveryAction.ABORT
        if confidence >= 0.6:
            return DriftRecoveryAction.REPLAN
        if confidence >= 0.3:
            return DriftRecoveryAction.RESET_SUBGOAL
        return DriftRecoveryAction.NONE
