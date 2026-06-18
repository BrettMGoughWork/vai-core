"""
Phase 2.15 — Governance-Integrated Drift & Confidence Tests
=============================================================

Validates drift detection and confidence scoring through the
MemoryGovernance layer (the integration point created in step 4.7).

Key differences from test_agent_drift.py:
- Subgoals and segments are created via governance.put_subgoal() /
  governance.put_segment() instead of being passed directly to
  run_agent_loop.
- Drift events are recorded through governance.record_drift(),
  which enforces cross-store consistency and structural validation.
- Confidence values are validated at the governance boundary.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.strategy.memory.drift_memory import DriftMemory
from src.strategy.memory.drift_memory_types import DriftEvent
from src.strategy.memory.governance.governance_errors import MemoryGovernanceError
from src.strategy.memory.governance.memory_governance import MemoryGovernance
from src.strategy.memory.plan_memory import PlanMemory
from src.strategy.memory.segment_memory import SegmentMemory
from src.strategy.memory.subgoal_memory import SubgoalMemory
from src.strategy.types.plan_segment import PlanSegment
from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def governance() -> MemoryGovernance:
    """Fresh MemoryGovernance with all four memory stores (no eviction)."""
    return MemoryGovernance(
        subgoal_memory=SubgoalMemory(),
        segment_memory=SegmentMemory(),
        plan_memory=PlanMemory(),
        drift_memory=DriftMemory(),
    )


def _put_subgoal(
    governance: MemoryGovernance,
    subgoal_id: str = "sg-1",
    goal: str = "Test goal",
) -> Subgoal:
    """Helper: create and store a subgoal via governance."""
    subgoal = Subgoal(
        subgoal_id=subgoal_id,
        goal=goal,
        context={},
        metadata={},
        state=SubgoalLifecycleState.ACTIVE,
    )
    governance.put_subgoal(subgoal)
    return subgoal


def _put_segment(
    governance: MemoryGovernance,
    subgoal_id: str = "sg-1",
    steps: list[str] | None = None,
) -> PlanSegment:
    """Helper: create and store a segment via governance."""
    segment = PlanSegment(
        subgoal_id=subgoal_id,
        steps=steps or ["step-a", "step-b"],
        context={},
        metadata={},
    )
    governance.put_segment(segment)
    return segment


# ======================================================================
# Tests
# ======================================================================


class TestGovernanceDrift:
    """Drift events recorded through the governance layer."""

    def test_record_drift_via_governance(self, governance: MemoryGovernance) -> None:
        """Put subgoal+segment, then record a drift event against them."""
        _put_subgoal(governance)
        seg = _put_segment(governance)

        event = DriftEvent(
            timestamp=1000,
            subgoal_id="sg-1",
            segment_id=seg.segment_id,
            step_id=None,
            signal_type="empty_steps",
            confidence=0.65,
            details={"empty_step_count": 2},
        )
        governance.record_drift(event)

        # Drift memory should now contain the event
        snapshot = governance._drift_memory.snapshot()
        assert len(snapshot.events) >= 1, "Drift event was not stored"
        assert any(e.timestamp == 1000 for e in snapshot.events)

    def test_drift_confidence_in_range(self, governance: MemoryGovernance) -> None:
        """Confidence values in [0.0, 1.0] are accepted."""
        _put_subgoal(governance)
        seg = _put_segment(governance)

        for confidence in (0.0, 0.25, 0.5, 0.75, 1.0):
            event = DriftEvent(
                timestamp=2000,
                subgoal_id="sg-1",
                segment_id=seg.segment_id,
                step_id=None,
                signal_type="shape_mismatch",
                confidence=confidence,
                details={"value": confidence},
            )
            governance.record_drift(event)  # should not raise

    def test_drift_rejects_out_of_range_confidence(
        self, governance: MemoryGovernance,
    ) -> None:
        """Confidence < 0.0 or > 1.0 is rejected by DriftEvent's own validation."""
        _put_subgoal(governance)
        _put_segment(governance)

        for bad_value in (-0.1, 1.5, 42.0):
            with pytest.raises(ValueError, match="confidence must be in"):
                DriftEvent(
                    timestamp=3000,
                    subgoal_id="sg-1",
                    segment_id="seg-1",
                    step_id=None,
                    signal_type="empty_steps",
                    confidence=bad_value,
                    details={},
                )

    def test_drift_requires_existing_subgoal(
        self, governance: MemoryGovernance,
    ) -> None:
        """Recording drift for a non-existent subgoal raises."""
        _put_subgoal(governance)
        _put_segment(governance, subgoal_id="sg-1")

        event = DriftEvent(
            timestamp=4000,
            subgoal_id="sg-nonexistent",
            segment_id="seg-1",
            step_id=None,
            signal_type="goal_divergence",
            confidence=0.5,
            details={},
        )
        with pytest.raises(MemoryGovernanceError):
            governance.record_drift(event)

    def test_drift_without_segment(self, governance: MemoryGovernance) -> None:
        """Drift at the subgoal level (no segment_id) is valid."""
        _put_subgoal(governance)

        event = DriftEvent(
            timestamp=5000,
            subgoal_id="sg-1",
            segment_id=None,
            step_id=None,
            signal_type="goal_divergence",
            confidence=0.8,
            details={"expected": "X", "actual": "Y"},
        )
        governance.record_drift(event)  # should not raise

    def test_multiple_drift_events_stored(self, governance: MemoryGovernance) -> None:
        """Multiple drift events accumulate in drift memory."""
        _put_subgoal(governance)
        seg = _put_segment(governance)

        events = [
            DriftEvent(timestamp=i, subgoal_id="sg-1", segment_id=seg.segment_id,
                       step_id=None, signal_type="empty_steps",
                       confidence=0.3 + i * 0.1, details={})
            for i in range(3)
        ]
        for e in events:
            governance.record_drift(e)

        snapshot = governance._drift_memory.snapshot()
        assert len(snapshot.events) >= 3, (
            f"Expected at least 3 drift events, got {len(snapshot.events)}"
        )


class TestConfidenceScoring:
    """Confidence scoring through governance integration."""

    def test_low_confidence_accepted(self, governance: MemoryGovernance) -> None:
        """Very low confidence (0.01) near zero is accepted."""
        _put_subgoal(governance)
        event = DriftEvent(
            timestamp=6000,
            subgoal_id="sg-1",
            segment_id=None,
            step_id=None,
            signal_type="behavioural",
            confidence=0.01,
            details={},
        )
        governance.record_drift(event)

    def test_high_confidence_accepted(self, governance: MemoryGovernance) -> None:
        """Very high confidence (1.0) is accepted."""
        _put_subgoal(governance)
        event = DriftEvent(
            timestamp=7000,
            subgoal_id="sg-1",
            segment_id=None,
            step_id=None,
            signal_type="structural",
            confidence=1.0,
            details={},
        )
        governance.record_drift(event)

    def test_confidence_is_float(self, governance: MemoryGovernance) -> None:
        """Confidence values are stored as float and accessible."""
        _put_subgoal(governance)
        seg = _put_segment(governance)

        event = DriftEvent(
            timestamp=8000,
            subgoal_id="sg-1",
            segment_id=seg.segment_id,
            step_id=None,
            signal_type="shape_mismatch",
            confidence=0.42,
            details={"reason": "step count mismatch"},
        )
        governance.record_drift(event)

        # Verify the event is stored with the correct confidence
        stored = governance._drift_memory.snapshot().events
        assert len(stored) >= 1
        # Check the latest event matches
        found = [e for e in stored if e.timestamp == 8000]
        assert len(found) == 1, f"Expected exactly 1 event at ts=8000, got {len(found)}"
        assert found[0].confidence == 0.42

    def test_get_drift_events_by_subgoal(self, governance: MemoryGovernance) -> None:
        """snapshot().events can be filtered by subgoal_id."""
        # Create two subgoals
        _put_subgoal(governance, subgoal_id="sg-a", goal="Goal A")
        _put_subgoal(governance, subgoal_id="sg-b", goal="Goal B")
        _put_segment(governance, subgoal_id="sg-a")
        _put_segment(governance, subgoal_id="sg-b")

        # Record drift for sg-a
        governance.record_drift(DriftEvent(
            timestamp=9000, subgoal_id="sg-a", segment_id=None,
            step_id=None, signal_type="empty_steps",
            confidence=0.5, details={},
        ))

        all_events = governance._drift_memory.snapshot().events
        a_events = [e for e in all_events if e.subgoal_id == "sg-a"]
        b_events = [e for e in all_events if e.subgoal_id == "sg-b"]

        assert len(a_events) >= 1, "Expected drift events for sg-a"
        assert len(b_events) == 0, "Expected no drift events for sg-b"

    def test_drift_event_round_trip(self, governance: MemoryGovernance) -> None:
        """A DriftEvent put through governance is retrievable with all fields."""
        _put_subgoal(governance)
        seg = _put_segment(governance)

        original = DriftEvent(
            timestamp=10000,
            subgoal_id="sg-1",
            segment_id=seg.segment_id,
            step_id="step-a",
            signal_type="empty_steps",
            confidence=0.55,
            details={"empty_count": 2, "expected": 3, "actual": 0},
        )
        governance.record_drift(original)

        stored = governance._drift_memory.snapshot().events
        found = [e for e in stored if e.timestamp == 10000]
        assert len(found) == 1
        retrieved = found[0]

        assert retrieved.subgoal_id == "sg-1"
        assert retrieved.segment_id == seg.segment_id
        assert retrieved.step_id == "step-a"
        assert retrieved.signal_type == "empty_steps"
        assert retrieved.confidence == 0.55
        assert retrieved.details.get("empty_count") == 2
