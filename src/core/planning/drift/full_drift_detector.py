from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from src.core.memory.drift_memory import DriftMemory
from src.core.memory.drift_memory_types import DriftEvent
from src.core.memory.governance.validation import validate_drift_event
from src.core.memory.governance.governance_errors import GovernanceViolation

from src.core.planning.drift.drift_context import DriftContext
from src.core.planning.drift.drift_types import (
    DriftClassification,
    DriftConfirmation,
    DriftSignal,
    DriftSignalClass,
    DriftTrigger,
)
from src.core.planning.drift.drift_signal_collectors import (
    DRIFT_SIGNAL_TYPE,
    collect_structural_signals,
    collect_behavioural_signals,
    collect_temporal_signals,
)


# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

_SEVERITY_BASE_CONFIDENCE: Dict[str, float] = {
    "high":   0.9,
    "medium": 0.6,
    "low":    0.3,
}

_SEVERITY_SCORE: Dict[str, int] = {
    "high":   3,
    "medium": 2,
    "low":    1,
}

# count_factor = min(1.0, COUNT_BASE + COUNT_STEP * n_signals)
# 5 signals → 1.0
_COUNT_BASE:  float = 0.7
_COUNT_STEP:  float = 0.06

# diversity_factor = DIVERSITY_BASE + DIVERSITY_STEP * n_classes  (1, 2, or 3 classes)
_DIVERSITY_BASE: float = 0.8
_DIVERSITY_STEP: float = 0.1

# Confirmation decay per cycle-age (most recent = 0 age)
_DECAY_PER_CYCLE: float = 0.2
_DECAY_MINIMUM:   float = 0.3


# ---------------------------------------------------------------------------
# Pure scoring functions
# ---------------------------------------------------------------------------

def compute_confidence(signals: List[DriftSignal]) -> float:
    """
    Deterministic confidence score in [0.0, 1.0] for a set of DriftSignals.

    Based on:
      - Severity distribution (weighted average of per-signal base confidence)
      - Signal count (logarithmic saturation — 5 signals → factor 1.0)
      - Signal diversity (how many distinct signal classes are represented)
    """
    if not signals:
        return 0.0

    severity_avg = sum(
        _SEVERITY_BASE_CONFIDENCE.get(s.severity, 0.3) for s in signals
    ) / len(signals)

    count_factor = min(1.0, _COUNT_BASE + _COUNT_STEP * len(signals))

    n_classes = len({s.signal_class for s in signals})
    diversity_factor = _DIVERSITY_BASE + _DIVERSITY_STEP * n_classes

    return min(1.0, severity_avg * count_factor * diversity_factor)


def classify_drift(signals: List[DriftSignal]) -> DriftClassification:
    """
    Deterministic drift classification from a set of DriftSignals.

    Score = sum of per-signal severity weights + diversity bonus.
    Thresholds:
      score == 0           → NO_DRIFT
      1  ≤ score < 5       → MINOR_DRIFT
      5  ≤ score < 10      → MODERATE_DRIFT
      10 ≤ score < 15      → SEVERE_DRIFT
      score >= 15          → CRITICAL_DRIFT
    """
    if not signals:
        return DriftClassification.NO_DRIFT

    severity_score = sum(_SEVERITY_SCORE.get(s.severity, 1) for s in signals)
    diversity_bonus = len({s.signal_class for s in signals})
    total = severity_score + diversity_bonus

    if total >= 15:
        return DriftClassification.CRITICAL_DRIFT
    if total >= 10:
        return DriftClassification.SEVERE_DRIFT
    if total >= 5:
        return DriftClassification.MODERATE_DRIFT
    if total >= 1:
        return DriftClassification.MINOR_DRIFT
    return DriftClassification.NO_DRIFT


# ---------------------------------------------------------------------------
# Multi-cycle confirmation buffer (stateful, internal)
# ---------------------------------------------------------------------------

class ConfirmationBuffer:
    """
    Tracks drift signals across cycles and determines when drift is confirmed.

    Confirmation semantics:
      - Drift is confirmed only after `confirmation_cycles` consecutive cycles
        each producing at least one signal.
      - Confidence is a decay-weighted average across cycle confidences.
      - If `cooldown_cycles` consecutive cycles produce no signals, the buffer resets.

    This class is intentionally stateful — multi-cycle confirmation requires it.
    Its outputs (DriftConfirmation) are pure frozen dataclasses.
    """

    def __init__(
        self,
        confirmation_cycles: int = 2,
        cooldown_cycles: int = 3,
    ) -> None:
        if confirmation_cycles < 1:
            raise ValueError(f"confirmation_cycles must be >= 1, got {confirmation_cycles}")
        if cooldown_cycles < 1:
            raise ValueError(f"cooldown_cycles must be >= 1, got {cooldown_cycles}")
        self._confirmation_cycles = confirmation_cycles
        self._cooldown_cycles = cooldown_cycles
        self._history: List[List[DriftSignal]] = []   # oldest-first
        self._clean_cycles: int = 0

    # ------------------------------------------------------------------
    # Core operation
    # ------------------------------------------------------------------

    def observe(self, signals: List[DriftSignal]) -> DriftConfirmation:
        """
        Record one detection cycle.  Returns the current DriftConfirmation.

        If signals is empty, increments the clean-cycle counter; after
        `cooldown_cycles` clean cycles, the buffer resets completely.

        If signals is non-empty, appends to history and resets clean-cycle count.
        History is trimmed to keep only the most recent `confirmation_cycles` entries.
        """
        if not signals:
            self._clean_cycles += 1
            if self._clean_cycles >= self._cooldown_cycles:
                self._history.clear()
                self._clean_cycles = 0
        else:
            self._clean_cycles = 0
            self._history.append(list(signals))
            # Keep only the most recent `confirmation_cycles` entries
            if len(self._history) > self._confirmation_cycles:
                self._history = self._history[-self._confirmation_cycles:]

        return self._build_confirmation()

    # ------------------------------------------------------------------
    # Snapshot / restore (pure, deterministic)
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict:
        """Return a JSON-safe representation of the buffer state."""
        return {
            "confirmation_cycles": self._confirmation_cycles,
            "cooldown_cycles": self._cooldown_cycles,
            "clean_cycles": self._clean_cycles,
            "history": [
                [
                    {
                        "type": s.type,
                        "severity": s.severity,
                        "timestamp": s.timestamp,
                        "signal_class": s.signal_class,
                        "metadata": s.metadata,
                    }
                    for s in cycle
                ]
                for cycle in self._history
            ],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_confirmation(self) -> DriftConfirmation:
        confirmed_cycles = len(self._history)
        confirmed = confirmed_cycles >= self._confirmation_cycles

        confidence = self._weighted_confidence()

        all_signals: List[DriftSignal] = [s for cycle in self._history for s in cycle]
        history_tuple: Tuple[Tuple[DriftSignal, ...], ...] = tuple(
            tuple(cycle) for cycle in self._history
        )

        return DriftConfirmation(
            confirmed=confirmed,
            confidence=confidence,
            cycles_observed=confirmed_cycles,
            signals=tuple(all_signals),
            history=history_tuple,
        )

    def _weighted_confidence(self) -> float:
        """
        Compute decay-weighted average confidence across history cycles.
        Most recent cycle has weight 1.0; each older cycle loses DECAY_PER_CYCLE.
        Minimum weight is DECAY_MINIMUM.
        """
        if not self._history:
            return 0.0

        n = len(self._history)
        weighted_sum = 0.0
        total_weight = 0.0

        for i, cycle_signals in enumerate(self._history):
            age = n - i - 1  # 0 = most recent
            decay = max(_DECAY_MINIMUM, 1.0 - _DECAY_PER_CYCLE * age)
            c = compute_confidence(cycle_signals)
            weighted_sum += decay * c
            total_weight += decay

        return min(1.0, weighted_sum / total_weight) if total_weight > 0.0 else 0.0


# ---------------------------------------------------------------------------
# FullDriftDetector
# ---------------------------------------------------------------------------

class FullDriftDetector:
    """
    Multi-signal, multi-cycle drift detection engine for Stratum-2.

    Combines structural, behavioural, and temporal signals into a unified
    drift classification with confidence scoring and multi-step confirmation.

    Design contract:
      - detect() is the primary entry point; call once per cycle.
      - write_to_memory() should be called by the caller when confirmation.confirmed
        is True AND the caller decides to record the event.  Never call it
        from inside detect() — this prevents self-reinforcing loops in DriftMemory.
      - Signal collection reads from ctx.drift_memory (if provided) but NEVER
        writes to it.  All writes are performed by write_to_memory().

    Pure, deterministic, no side effects on outputs.
    No LLM calls, no inference, no semantic analysis.
    """

    def __init__(
        self,
        confirmation_cycles: int = 2,
        cooldown_cycles: int = 3,
    ) -> None:
        self._buffer = ConfirmationBuffer(confirmation_cycles, cooldown_cycles)

    # ------------------------------------------------------------------
    # Primary detection cycle
    # ------------------------------------------------------------------

    def detect(self, ctx: DriftContext) -> DriftConfirmation:
        """
        Run one full detection cycle against the provided context.

        Collects structural, behavioural, and temporal signals, then
        passes them to the confirmation buffer.

        Returns a DriftConfirmation reflecting the current multi-cycle state.
        Does NOT write to DriftMemory — that is the caller's responsibility.
        """
        structural  = collect_structural_signals(ctx)
        behavioural = collect_behavioural_signals(ctx)
        temporal    = collect_temporal_signals(ctx)
        all_signals = structural + behavioural + temporal

        return self._buffer.observe(all_signals)

    # ------------------------------------------------------------------
    # DriftTrigger production
    # ------------------------------------------------------------------

    def get_trigger(
        self,
        confirmation: DriftConfirmation,
        ctx: DriftContext,
    ) -> Optional[DriftTrigger]:
        """
        Produce a DriftTrigger from a confirmed DriftConfirmation.

        Returns None if confirmation.confirmed is False.
        The trigger is consumed by PlanRepair (2.5.1).
        """
        if not confirmation.confirmed:
            return None

        signals = list(confirmation.signals)
        classification = classify_drift(signals)

        structural_sigs  = [s for s in signals if s.signal_class == DriftSignalClass.STRUCTURAL.value]
        behavioural_sigs = [s for s in signals if s.signal_class == DriftSignalClass.BEHAVIOURAL.value]
        temporal_sigs    = [s for s in signals if s.signal_class == DriftSignalClass.TEMPORAL.value]

        structural_ctx: dict = {
            "signal_count": len(structural_sigs),
            "types": [s.type for s in structural_sigs],
        }
        behavioural_ctx: dict = {
            "signal_count": len(behavioural_sigs),
            "types": [s.type for s in behavioural_sigs],
        }
        temporal_ctx: dict = {
            "signal_count": len(temporal_sigs),
            "types": [s.type for s in temporal_sigs],
        }

        return DriftTrigger(
            classification=classification.value,
            confidence=confirmation.confidence,
            cycles_observed=confirmation.cycles_observed,
            structural_context=structural_ctx,
            behavioural_context=behavioural_ctx,
            temporal_context=temporal_ctx,
        )

    # ------------------------------------------------------------------
    # DriftMemory governed write path
    # ------------------------------------------------------------------

    def write_to_memory(
        self,
        confirmation: DriftConfirmation,
        ctx: DriftContext,
        drift_memory: DriftMemory,
    ) -> List[GovernanceViolation]:
        """
        Write a DriftEvent to drift_memory if confirmation.confirmed is True.

        Uses the governed write path: validate_drift_event() must pass before
        recording.  Returns an empty list on success, or the governance
        violations that blocked the write.

        Returns an empty list immediately if not confirmed (no write attempted).

        CALLER RESPONSIBILITY: Call this AFTER detect() — never inside it.
        DriftMemory passed here must NOT be the same object whose data was
        read inside the detection cycle, OR the read must have completed
        before this call (which is guaranteed when this is called after detect()).
        """
        if not confirmation.confirmed:
            return []

        classification = classify_drift(list(confirmation.signals)).value
        try:
            event = DriftEvent(
                timestamp=ctx.timestamp,
                subgoal_id=ctx.subgoal_id,
                segment_id=None,   # plan-level event; plan_id goes in details
                step_id=None,
                signal_type=DRIFT_SIGNAL_TYPE,
                confidence=confirmation.confidence,
                details={
                    "classification": classification,
                    "cycles_observed": confirmation.cycles_observed,
                    "signal_count": len(confirmation.signals),
                    "plan_id": ctx.plan_id,
                },
            )
        except ValueError as exc:
            return [GovernanceViolation(
                rule="invalid_drift_event",
                field="subgoal_id",
                message=str(exc),
                record_id=ctx.subgoal_id or None,
            )]

        violations = validate_drift_event(event)
        if not violations:
            drift_memory.record(event)
        return violations

    # ------------------------------------------------------------------
    # Public wrappers for pure functions (testability + API completeness)
    # ------------------------------------------------------------------

    def compute_confidence(self, signals: List[DriftSignal]) -> float:
        """Deterministic confidence score for a set of DriftSignals."""
        return compute_confidence(signals)

    def classify(self, signals: List[DriftSignal]) -> DriftClassification:
        """Deterministic classification for a set of DriftSignals."""
        return classify_drift(signals)

    def buffer_snapshot(self) -> Dict:
        """Return the current confirmation buffer state as a JSON-safe dict."""
        return self._buffer.snapshot()
