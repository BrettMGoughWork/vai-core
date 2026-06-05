"""
Tests for Phase 2.6.5 — Behavioural Drift Repair.

Covers:
  - BehaviouralDriftRepair frozen dataclass validation
  - repair_behavioural_drift() pure function
  - No‑drift → needs_repair=False, empty actions
  - Single / multiple signal → correct action mapping
  - Deterministic action ordering (sorted by signal type name)
  - Defensive copy of reasons
  - Confidence correctly propagated
  - Non‑mutation invariants
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.drift.behavioural_signal_types import (
    BehaviouralDriftClassification,
    BehaviouralDriftRepair,
    BehaviouralSignal,
    BehaviouralSignalType,
)
from src.core.planning.drift.behavioural_drift_repair import (
    repair_behavioural_drift,
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
) -> SegmentMemoryRecord:
    return SegmentMemoryRecord(
        segment_id=segment_id,
        parent_id=None,
        subgoal_id=subgoal_id,
        state=None,
        content=["step-1"],
        created_at=NOW,
        context={},
        metadata={},
        last_output=None,
        behavioural_signals=signals or [],
    )


def _classification(
    drift_status: str,
    confidence: float,
    reasons: List[BehaviouralSignal] | None = None,
) -> BehaviouralDriftClassification:
    return BehaviouralDriftClassification(
        drift_status=drift_status,
        confidence=confidence,
        reasons=reasons or [],
    )


# ============================================================================
# BehaviouralDriftRepair dataclass
# ============================================================================


class TestBehaviouralDriftRepair:
    """Tests for the BehaviouralDriftRepair frozen dataclass."""

    def test_no_repair_construction(self) -> None:
        r = BehaviouralDriftRepair(
            needs_repair=False,
            repair_actions=[],
            confidence=0.0,
            reasons=[],
        )
        assert r.needs_repair is False
        assert r.repair_actions == []
        assert r.confidence == 0.0
        assert r.reasons == []

    def test_repair_construction(self) -> None:
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        r = BehaviouralDriftRepair(
            needs_repair=True,
            repair_actions=["verify declared vs executed capability"],
            confidence=0.25,
            reasons=[sig],
        )
        assert r.needs_repair is True
        assert len(r.repair_actions) == 1
        assert r.confidence == 0.25

    def test_frozen(self) -> None:
        r = BehaviouralDriftRepair(
            needs_repair=False,
            repair_actions=[],
            confidence=0.0,
            reasons=[],
        )
        with pytest.raises(Exception):
            r.needs_repair = True  # type: ignore[misc]

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            BehaviouralDriftRepair(
                needs_repair=False,
                repair_actions=[],
                confidence=1.5,
                reasons=[],
            )

    def test_repair_actions_defensive_copy(self) -> None:
        actions = ["action-a"]
        r = BehaviouralDriftRepair(
            needs_repair=True,
            repair_actions=actions,
            confidence=0.5,
            reasons=[],
        )
        actions.append("action-b")
        assert r.repair_actions == ["action-a"]

    def test_reasons_defensive_copy(self) -> None:
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        reasons = [sig]
        r = BehaviouralDriftRepair(
            needs_repair=True,
            repair_actions=["action"],
            confidence=0.5,
            reasons=reasons,
        )
        reasons.append(_signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE))
        assert len(r.reasons) == 1


# ============================================================================
# repair_behavioural_drift — core logic
# ============================================================================

# Action strings expected per signal type
_ACTION = {
    BehaviouralSignalType.WRONG_CAPABILITY: "verify declared vs executed capability",
    BehaviouralSignalType.WRONG_OUTPUT_SHAPE: "validate output shape against declared schema",
    BehaviouralSignalType.WRONG_OUTPUT_SEMANTICS: "inspect semantic fields for correctness",
    BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT: "audit side-effect declarations vs execution",
}


class TestRepairBehaviouralDrift:
    """Tests for the repair_behavioural_drift() pure function."""

    # ── no drift ───────────────────────────────────────────────────────

    def test_no_drift_no_repair(self) -> None:
        record = _record(signals=[])
        classification = _classification("no_drift", 0.0)
        result = repair_behavioural_drift(record, classification)
        assert result.needs_repair is False
        assert result.repair_actions == []
        assert result.confidence == 0.0
        assert result.reasons == []

    def test_no_drift_even_with_stale_record_signals(self) -> None:
        """record.behavioural_signals is ignored — only classification matters."""
        record = _record(
            signals=[_signal(BehaviouralSignalType.WRONG_CAPABILITY)]
        )
        classification = _classification("no_drift", 0.0)
        result = repair_behavioural_drift(record, classification)
        assert result.needs_repair is False
        assert result.repair_actions == []

    # ── single signal → single action ──────────────────────────────────

    @pytest.mark.parametrize(
        "signal_type, expected_action",
        list(_ACTION.items()),
    )
    def test_single_signal_maps_to_correct_action(
        self, signal_type: BehaviouralSignalType, expected_action: str
    ) -> None:
        sig = _signal(signal_type)
        record = _record(signals=[sig])
        classification = _classification("behavioural_drift", 0.25, [sig])
        result = repair_behavioural_drift(record, classification)
        assert result.needs_repair is True
        assert result.repair_actions == [expected_action]
        assert result.confidence == 0.25

    # ── multiple signals → multiple actions ────────────────────────────

    def test_two_signals_two_actions(self) -> None:
        signals = [
            _signal(BehaviouralSignalType.WRONG_CAPABILITY),
            _signal(BehaviouralSignalType.WRONG_OUTPUT_SEMANTICS),
        ]
        record = _record(signals=signals)
        classification = _classification("behavioural_drift", 0.5, signals)
        result = repair_behavioural_drift(record, classification)
        assert result.needs_repair is True
        assert len(result.repair_actions) == 2

    def test_actions_sorted_alphabetically(self) -> None:
        """Actions must be in deterministic order: sorted by signal type name."""
        signals = [
            _signal(BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT),
            _signal(BehaviouralSignalType.WRONG_CAPABILITY),
            _signal(BehaviouralSignalType.WRONG_OUTPUT_SEMANTICS),
            _signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE),
        ]
        record = _record(signals=signals)
        classification = _classification("behavioural_drift", 1.0, signals)
        result = repair_behavioural_drift(record, classification)

        # Sorted by signal type name:
        # UNEXPECTED_SIDE_EFFECT comes first, then WRONG_CAPABILITY, etc.
        expected_order = sorted(
            [_ACTION[s.signal_type] for s in signals]
        )
        assert result.repair_actions == expected_order

    def test_all_four_signals_all_actions_sorted(self) -> None:
        signals = [
            _signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE),
            _signal(BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT),
            _signal(BehaviouralSignalType.WRONG_CAPABILITY),
            _signal(BehaviouralSignalType.WRONG_OUTPUT_SEMANTICS),
        ]
        record = _record(signals=signals)
        classification = _classification("behavioural_drift", 1.0, signals)
        result = repair_behavioural_drift(record, classification)
        assert len(result.repair_actions) == 4
        # Verify sorted order
        expected = sorted([_ACTION[s.signal_type] for s in signals])
        assert result.repair_actions == expected

    def test_duplicate_signal_type_deduplicated(self) -> None:
        """Duplicate signal types → only one action per type."""
        signals = [
            _signal(BehaviouralSignalType.WRONG_CAPABILITY),
            _signal(BehaviouralSignalType.WRONG_CAPABILITY),
        ]
        record = _record(signals=signals)
        classification = _classification("behavioural_drift", 0.5, signals)
        result = repair_behavioural_drift(record, classification)
        assert len(result.repair_actions) == 1
        assert result.repair_actions == [_ACTION[BehaviouralSignalType.WRONG_CAPABILITY]]

    # ── confidence propagation ─────────────────────────────────────────

    def test_confidence_copied_from_classification(self) -> None:
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        record = _record(signals=[sig])
        classification = _classification("behavioural_drift", 0.75, [sig])
        result = repair_behavioural_drift(record, classification)
        assert result.confidence == 0.75

    # ── reasons defensive copy ─────────────────────────────────────────

    def test_reasons_defensive_copy(self) -> None:
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        reasons = [sig]
        record = _record(signals=reasons)
        classification = _classification("behavioural_drift", 0.25, reasons)
        result = repair_behavioural_drift(record, classification)
        # Mutate the original list — result should be unaffected
        reasons.append(_signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE))
        assert len(result.reasons) == 1

    # ── determinism ────────────────────────────────────────────────────

    def test_deterministic_output(self) -> None:
        signals = [
            _signal(BehaviouralSignalType.WRONG_CAPABILITY),
            _signal(BehaviouralSignalType.WRONG_OUTPUT_SHAPE),
        ]
        record1 = _record(signals=signals)
        record2 = _record(signals=signals)
        classification = _classification("behavioural_drift", 0.5, signals)
        r1 = repair_behavioural_drift(record1, classification)
        r2 = repair_behavioural_drift(record2, classification)
        assert r1.needs_repair == r2.needs_repair
        assert r1.repair_actions == r2.repair_actions
        assert r1.confidence == r2.confidence

    # ── non‑mutation of record ─────────────────────────────────────────

    def test_does_not_mutate_record(self) -> None:
        sig = _signal(BehaviouralSignalType.WRONG_CAPABILITY)
        record = _record(signals=[sig])
        original_signals = list(record.behavioural_signals)
        original_metadata = dict(record.metadata)
        classification = _classification("behavioural_drift", 0.25, [sig])

        repair_behavioural_drift(record, classification)

        assert list(record.behavioural_signals) == original_signals
        assert dict(record.metadata) == original_metadata

    # ── invalid classification still handled ───────────────────────────

    def test_behavioural_drift_with_no_signals_repairs_anyway(self) -> None:
        """If classification says behavioural_drift but has no reasons,
        needs_repair is True but actions are empty."""
        record = _record(signals=[])
        classification = _classification("behavioural_drift", 0.0, [])
        result = repair_behavioural_drift(record, classification)
        assert result.needs_repair is True
        assert result.repair_actions == []
