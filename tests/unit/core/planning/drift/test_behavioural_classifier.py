"""
Tests for Phase 2.6.4 — Behavioural Drift Classifier.

Covers:
  - classify_behavioural_drift() pure function
  - BehaviouralDriftClassification dataclass validation
  - Confidence formula (base + streak, capped at 1.0)
  - Streak metadata handling (default, invalid, edge cases)
  - Determinism and non-mutation invariants
"""
from __future__ import annotations

import datetime
import math
from typing import Any, Dict, List

import pytest

from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.drift.behavioural_signal_types import (
    BehaviouralDriftClassification,
    BehaviouralSignal,
    BehaviouralSignalType,
)
from src.core.planning.drift.behavioural_signal_classifier import (
    classify_behavioural_drift,
)


# ── helpers ─────────────────────────────────────────────────────────────────

NOW = "2025-06-05T00:00:00+00:00"


def _signal(
    signal_type: BehaviouralSignalType,
    segment_id: str = "seg-1",
    subgoal_id: str = "sg-1",
    details: Dict[str, Any] | None = None,
    timestamp: str = NOW,
) -> BehaviouralSignal:
    """Create a BehaviouralSignal with convenient defaults."""
    return BehaviouralSignal(
        signal_type=signal_type,
        segment_id=segment_id,
        subgoal_id=subgoal_id,
        details=details or {},
        timestamp=timestamp,
    )


def _record(
    *,
    segment_id: str = "seg-1",
    subgoal_id: str = "sg-1",
    signals: List[BehaviouralSignal] | None = None,
    streak: int | None = None,
    extra_metadata: Dict[str, Any] | None = None,
) -> SegmentMemoryRecord:
    """Build a SegmentMemoryRecord with behavioural_signals and optional streak."""
    metadata: Dict[str, Any] = dict(extra_metadata or {})
    if streak is not None:
        metadata["behavioural_drift_streak"] = streak

    return SegmentMemoryRecord(
        segment_id=segment_id,
        parent_id=None,
        subgoal_id=subgoal_id,
        state=None,
        content=["step-1"],
        created_at="2025-06-05T00:00:00+00:00",
        context={},
        metadata=metadata,
        last_output=None,
        behavioural_signals=signals or [],
    )


# ============================================================================
# BehaviouralDriftClassification dataclass
# ============================================================================


class TestBehaviouralDriftClassification:
    """Tests for the BehaviouralDriftClassification dataclass itself."""

    def test_no_drift_construction(self) -> None:
        c = BehaviouralDriftClassification(
            drift_status="no_drift",
            confidence=0.0,
            reasons=[],
        )
        assert c.drift_status == "no_drift"
        assert c.confidence == 0.0
        assert c.reasons == []

    def test_drift_construction(self) -> None:
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        c = BehaviouralDriftClassification(
            drift_status="behavioural_drift",
            confidence=0.25,
            reasons=[sig],
        )
        assert c.drift_status == "behavioural_drift"
        assert c.confidence == 0.25
        assert c.reasons == [sig]

    def test_frozen(self) -> None:
        c = BehaviouralDriftClassification(
            drift_status="no_drift",
            confidence=0.0,
            reasons=[],
        )
        with pytest.raises(Exception):
            c.confidence = 1.0  # type: ignore[misc]

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            BehaviouralDriftClassification(
                drift_status="no_drift",
                confidence=1.5,
                reasons=[],
            )

    def test_invalid_drift_status_raises(self) -> None:
        with pytest.raises(ValueError, match="drift_status"):
            BehaviouralDriftClassification(
                drift_status="invalid_status",  # type: ignore[arg-type]
                confidence=0.5,
                reasons=[],
            )

    def test_reasons_is_defensive_copy(self) -> None:
        """Mutating the list passed in doesn't affect the frozen instance."""
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        reasons = [sig]
        c = BehaviouralDriftClassification(
            drift_status="behavioural_drift",
            confidence=0.25,
            reasons=reasons,
        )
        reasons.append(_signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE))
        # The frozen instance should still have only 1
        assert len(c.reasons) == 1


# ============================================================================
# classify_behavioural_drift — core logic
# ============================================================================


class TestClassifyBehaviouralDrift:
    """Tests for the classify_behavioural_drift() pure function."""

    # ── no signals ──────────────────────────────────────────────────────

    def test_empty_signals_returns_no_drift(self) -> None:
        record = _record(signals=[])
        result = classify_behavioural_drift(record)
        assert result.drift_status == "no_drift"
        assert result.confidence == 0.0
        assert result.reasons == []

    def test_empty_signals_even_with_streak_returns_no_drift(self) -> None:
        """Streak doesn't matter if there are no signals in this segment."""
        record = _record(signals=[], streak=5)
        result = classify_behavioural_drift(record)
        assert result.drift_status == "no_drift"
        assert result.confidence == 0.0

    # ── signal count → confidence ───────────────────────────────────────

    def test_one_signal_confidence_0_25(self) -> None:
        record = _record(
            signals=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)]
        )
        result = classify_behavioural_drift(record)
        assert result.drift_status == "behavioural_drift"
        assert result.confidence == 0.25
        assert len(result.reasons) == 1

    def test_two_signals_confidence_0_5(self) -> None:
        record = _record(
            signals=[
                _signal(BehaviouralSignalType.WRONG_CAPABILITY),
                _signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE),
            ]
        )
        result = classify_behavioural_drift(record)
        assert result.drift_status == "behavioural_drift"
        assert result.confidence == 0.5
        assert len(result.reasons) == 2

    def test_three_signals_confidence_0_75(self) -> None:
        record = _record(
            signals=[
                _signal(BehaviouralSignalType.WRONG_CAPABILITY),
                _signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE),
                _signal(BehaviouralSignalType.WRONG_OUTPUT_SEMANTICS),
            ]
        )
        result = classify_behavioural_drift(record)
        assert result.confidence == 0.75

    def test_four_signals_confidence_1_0(self) -> None:
        record = _record(
            signals=[
                _signal(BehaviouralSignalType.WRONG_CAPABILITY),
                _signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE),
                _signal(BehaviouralSignalType.WRONG_OUTPUT_SEMANTICS),
                _signal(BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT),
            ]
        )
        result = classify_behavioural_drift(record)
        assert result.drift_status == "behavioural_drift"
        assert result.confidence == 1.0
        assert len(result.reasons) == 4

    # ── streak bonus ────────────────────────────────────────────────────

    def test_streak_zero_same_as_no_streak(self) -> None:
        """Explicit streak=0 gives same result as missing metadata."""
        record_no_streak = _record(
            signals=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)]
        )
        record_streak_0 = _record(
            signals=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)],
            streak=0,
        )
        r1 = classify_behavioural_drift(record_no_streak)
        r2 = classify_behavioural_drift(record_streak_0)
        assert r1.confidence == r2.confidence == 0.25

    def test_streak_of_1_adds_0_1(self) -> None:
        record = _record(
            signals=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)],
            streak=1,
        )
        result = classify_behavioural_drift(record)
        assert result.confidence == 0.35  # 0.25 + 0.1

    def test_streak_of_3_adds_0_3(self) -> None:
        record = _record(
            signals=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)],
            streak=3,
        )
        result = classify_behavioural_drift(record)
        assert result.confidence == 0.55  # 0.25 + 0.3

    def test_streak_cannot_push_above_1_0(self) -> None:
        """Confidence is capped at 1.0 regardless of streak."""
        record = _record(
            signals=[
                _signal(BehaviouralSignalType.WRONG_CAPABILITY),
                _signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE),
                _signal(BehaviouralSignalType.WRONG_OUTPUT_SEMANTICS),
                _signal(BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT),
            ],
            streak=100,
        )
        result = classify_behavioural_drift(record)
        assert result.confidence == 1.0

    def test_streak_and_four_signals_capped(self) -> None:
        """4 signals = 1.0 base; streak bonus pushes beyond 1.0 but is capped."""
        record = _record(
            signals=[
                _signal(BehaviouralSignalType.WRONG_CAPABILITY),
                _signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE),
                _signal(BehaviouralSignalType.WRONG_OUTPUT_SEMANTICS),
                _signal(BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT),
            ],
            streak=5,
        )
        result = classify_behavioural_drift(record)
        assert result.confidence == 1.0

    # ── streak metadata edge cases ──────────────────────────────────────

    def test_missing_streak_metadata_treated_as_zero(self) -> None:
        """No behavioural_drift_streak key → streak defaults to 0."""
        record = _record(
            signals=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)]
        )
        # No streak metadata at all
        result = classify_behavioural_drift(record)
        assert result.confidence == 0.25  # base only

    def test_streak_is_string_parsed_as_int(self) -> None:
        """String streaks like '3' are parsed as integers."""
        record = _record(
            signals=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)],
            extra_metadata={"behavioural_drift_streak": "3"},
        )
        result = classify_behavioural_drift(record)
        assert result.confidence == 0.55  # 0.25 + 0.3

    def test_invalid_streak_value_treated_as_zero(self) -> None:
        """Non-numeric streak → treated as 0."""
        record = _record(
            signals=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)],
            extra_metadata={"behavioural_drift_streak": "not-a-number"},
        )
        result = classify_behavioural_drift(record)
        assert result.confidence == 0.25  # base only, no bonus

    def test_negative_streak_no_penalty(self) -> None:
        """Negative streak → max(0, streak) prevents penalty."""
        record = _record(
            signals=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)],
            streak=-5,
        )
        result = classify_behavioural_drift(record)
        assert result.confidence == 0.25  # base only, no penalty

    # ── determinism ─────────────────────────────────────────────────────

    def test_deterministic_output(self) -> None:
        """Same input always produces the same output."""
        signals = [
            _signal(BehaviouralSignalType.WRONG_CAPABILITY),
            _signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE),
        ]
        record1 = _record(signals=signals, streak=2)
        record2 = _record(signals=signals, streak=2)
        r1 = classify_behavioural_drift(record1)
        r2 = classify_behavioural_drift(record2)
        assert r1.drift_status == r2.drift_status
        assert r1.confidence == r2.confidence
        assert len(r1.reasons) == len(r2.reasons)

    # ── non-mutation invariants ─────────────────────────────────────────

    def test_does_not_mutate_record(self) -> None:
        """Classifier is pure — it does not modify the SegmentMemoryRecord."""
        signals = [_signal(BehaviouralSignalType.WRONG_CAPABILITY)]
        record = _record(signals=signals, streak=1)
        original_signals = list(record.behavioural_signals)
        original_metadata = dict(record.metadata)

        classify_behavioural_drift(record)

        assert list(record.behavioural_signals) == original_signals
        assert dict(record.metadata) == original_metadata

    def test_does_not_mutate_signal_objects(self) -> None:
        """The returned reasons contain the same signal objects (frozen)."""
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        record = _record(signals=[sig])
        result = classify_behavioural_drift(record)
        assert result.reasons[0] is sig  # same immutable object

    # ── confidence precision ────────────────────────────────────────────

    def test_confidence_no_floating_point_noise(self) -> None:
        """Confidence values are clean (no 0.30000000000000004 etc.)."""
        record = _record(
            signals=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)],
            streak=3,
        )
        result = classify_behavioural_drift(record)
        # 0.25 + 0.3 = 0.55 — should be exact
        assert math.isclose(result.confidence, 0.55)
