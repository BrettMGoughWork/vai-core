from __future__ import annotations

import copy
import json

import pytest

from src.core.planning.segments.execution import (
    SegmentLifecycle,
    SegmentExecutionState,
    transition_segment_state,
    advance_segment_index,
    update_segment_execution_state,
    segment_progress_summary,
    segment_completion_summary,
)


# ──────────────────────────────────────────────────────────────────────────────
# SegmentState Enum
# ──────────────────────────────────────────────────────────────────────────────

class TestSegmentStateEnum:
    """The enum must define exactly PENDING, ACTIVE, COMPLETE."""

    def test_values(self):
        assert SegmentLifecycle.PENDING == "pending"
        assert SegmentLifecycle.ACTIVE == "active"
        assert SegmentLifecycle.COMPLETE == "complete"

    def test_is_string_enum(self):
        assert isinstance(SegmentLifecycle.PENDING, str)
        assert issubclass(SegmentLifecycle, str)


# ──────────────────────────────────────────────────────────────────────────────
# transition_segment_state
# ──────────────────────────────────────────────────────────────────────────────

class TestTransitionSegmentState:
    """Deterministic state machine: pending → active → complete."""

    def test_pending_to_active(self):
        assert transition_segment_state("pending", False) == "active"
        assert transition_segment_state("pending", True) == "active"

    def test_active_stays_active(self):
        assert transition_segment_state("active", False) == "active"

    def test_active_to_complete(self):
        assert transition_segment_state("active", True) == "complete"

    def test_complete_stays_complete(self):
        assert transition_segment_state("complete", False) == "complete"
        assert transition_segment_state("complete", True) == "complete"

    def test_deterministic(self):
        """Same inputs must always produce same output."""
        for state in ("pending", "active", "complete"):
            for is_complete in (True, False):
                a = transition_segment_state(state, is_complete)
                b = transition_segment_state(copy.deepcopy(state), is_complete)
                assert a == b

    def test_invalid_state_raises(self):
        with pytest.raises(ValueError, match="Invalid segment state"):
            transition_segment_state("invalid", False)
        with pytest.raises(ValueError, match="Invalid segment state"):
            transition_segment_state("", False)
        with pytest.raises(ValueError, match="Invalid segment state"):
            transition_segment_state(None, False)

    def test_pure_no_mutation(self):
        """Function must not mutate its inputs."""
        state = "pending"
        saved = state
        transition_segment_state(state, True)
        assert state == saved

    def test_result_is_valid_enum(self):
        """All valid transitions must return valid SegmentState values."""
        for state in ("pending", "active", "complete"):
            for is_complete in (True, False):
                result = transition_segment_state(state, is_complete)
                assert result in (SegmentLifecycle.PENDING, SegmentLifecycle.ACTIVE, SegmentLifecycle.COMPLETE)
                assert isinstance(result, str)


# ──────────────────────────────────────────────────────────────────────────────
# advance_segment_index
# ──────────────────────────────────────────────────────────────────────────────

class TestAdvanceSegmentIndex:
    """Pure index advancement with clamping."""

    def test_advance_from_zero(self):
        assert advance_segment_index(0, 3) == 1
        assert advance_segment_index(0, 2) == 1

    def test_advance_mid_plan(self):
        assert advance_segment_index(1, 3) == 2

    def test_no_advance_at_final(self):
        """At the final segment, stay at current index."""
        assert advance_segment_index(2, 3) == 2
        assert advance_segment_index(3, 3) == 3

    def test_single_segment(self):
        """Single-segment plan: index stays at 0."""
        assert advance_segment_index(0, 1) == 0

    def test_zero_segments(self):
        """Zero segments: index unchanged."""
        assert advance_segment_index(0, 0) == 0
        assert advance_segment_index(5, 0) == 5

    def test_negative_index_raises(self):
        with pytest.raises(ValueError, match="current_index must be >= 0"):
            advance_segment_index(-1, 3)

    def test_negative_total_raises(self):
        with pytest.raises(ValueError, match="total_segments must be >= 0"):
            advance_segment_index(0, -1)

    def test_deterministic(self):
        for idx in range(5):
            for total in range(5):
                a = advance_segment_index(idx, total)
                b = advance_segment_index(idx, total)
                assert a == b

    def test_pure_no_mutation(self):
        idx = 2
        total = 5
        saved_idx = idx
        saved_total = total
        advance_segment_index(idx, total)
        assert idx == saved_idx
        assert total == saved_total


# ──────────────────────────────────────────────────────────────────────────────
# update_segment_execution_state
# ──────────────────────────────────────────────────────────────────────────────

class TestUpdateSegmentExecutionState:
    """Wrapper function combining transition + index advancement."""

    def test_pending_to_active_preserves_index(self):
        state = SegmentExecutionState(index=0, state="pending")
        result = update_segment_execution_state(state, is_complete=False, total_segments=3)
        assert result.state == "active"
        assert result.index == 0

    def test_active_to_complete_advances_index(self):
        state = SegmentExecutionState(index=0, state="active")
        result = update_segment_execution_state(state, is_complete=True, total_segments=3)
        assert result.state == "complete"
        assert result.index == 1

    def test_complete_stays_complete(self):
        state = SegmentExecutionState(index=1, state="complete")
        result = update_segment_execution_state(state, is_complete=True, total_segments=3)
        assert result.state == "complete"
        assert result.index == 1  # no further advancement

    def test_final_segment_no_advancement(self):
        """Completing the final segment: index stays at last segment."""
        state = SegmentExecutionState(index=2, state="active")
        result = update_segment_execution_state(state, is_complete=True, total_segments=3)
        assert result.state == "complete"
        assert result.index == 2

    def test_returns_new_instance(self):
        """Must return a new SegmentExecutionState, not mutate input."""
        state = SegmentExecutionState(index=0, state="pending")
        result = update_segment_execution_state(state, is_complete=True, total_segments=3)
        assert result is not state
        assert state.state == "pending"
        assert state.index == 0

    def test_deterministic(self):
        state = SegmentExecutionState(index=1, state="active")
        r1 = update_segment_execution_state(state, True, 4)
        r2 = update_segment_execution_state(SegmentExecutionState(index=1, state="active"), True, 4)
        assert r1 == r2

    def test_invalid_state_raises(self):
        state = SegmentExecutionState(index=0, state="invalid")
        with pytest.raises(ValueError):
            update_segment_execution_state(state, True, 3)

    def test_negative_index_raises(self):
        state = SegmentExecutionState(index=-1, state="pending")
        with pytest.raises(ValueError):
            update_segment_execution_state(state, True, 3)

    def test_immutable_result(self):
        """SegmentExecutionState is frozen — cannot mutate after creation."""
        result = update_segment_execution_state(
            SegmentExecutionState(index=0, state="pending"),
            True,
            3,
        )
        with pytest.raises(Exception):
            result.state = "pending"  # frozen dataclass


# ──────────────────────────────────────────────────────────────────────────────
# Structural Summary Hooks
# ──────────────────────────────────────────────────────────────────────────────

class TestStructuralSummaryHooks:
    """Placeholder hooks for Phase 2.11.2 — must be JSON-safe."""

    def test_progress_summary_keys(self):
        state = SegmentExecutionState(index=0, state="active")
        summary = segment_progress_summary(state)
        assert summary == {"index": 0, "state": "active"}

    def test_completion_summary_keys(self):
        state = SegmentExecutionState(index=2, state="complete")
        summary = segment_completion_summary(state)
        assert summary == {"is_complete": True}

        active = SegmentExecutionState(index=0, state="active")
        assert segment_completion_summary(active) == {"is_complete": False}

    def test_summaries_are_json_safe(self):
        state = SegmentExecutionState(index=0, state="active")
        json.dumps(segment_progress_summary(state))
        json.dumps(segment_completion_summary(state))

    def test_summaries_do_not_mutate_input(self):
        state = SegmentExecutionState(index=1, state="active")
        saved = copy.deepcopy(state)
        segment_progress_summary(state)
        segment_completion_summary(state)
        assert state == saved


# ──────────────────────────────────────────────────────────────────────────────
# Edge Cases
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Boundary and edge-case scenarios."""

    def test_zero_segments_transition(self):
        """Transitions are valid even with zero total segments."""
        state = SegmentExecutionState(index=0, state="pending")
        result = update_segment_execution_state(state, True, 0)
        assert result.state == "active"  # pending → active
        assert result.index == 0  # no advancement (0 segments)

    def test_zero_segments_complete(self):
        """Active segment completes with zero total."""
        state = SegmentExecutionState(index=0, state="active")
        result = update_segment_execution_state(state, True, 0)
        assert result.state == "complete"
        assert result.index == 0

    def test_large_segment_count(self):
        """Large total_segments should not break."""
        state = SegmentExecutionState(index=9998, state="active")
        result = update_segment_execution_state(state, True, 10000)
        assert result.state == "complete"
        assert result.index == 9999

    def test_default_execution_state(self):
        """Default SegmentExecutionState starts at index 0, pending."""
        state = SegmentExecutionState()
        assert state.index == 0
        assert state.state == "pending"

    def test_full_lifecycle(self):
        """Complete lifecycle: pending → active → complete."""
        state = SegmentExecutionState()

        # Step 1: Start execution
        state = update_segment_execution_state(state, is_complete=False, total_segments=2)
        assert state.state == "active"
        assert state.index == 0

        # Step 2: Segment 0 completes
        state = update_segment_execution_state(state, is_complete=True, total_segments=2)
        assert state.state == "complete"
        assert state.index == 1

        # Step 3: Next segment starts (new state from "complete" → stays complete)
        # In practice, the system would create a new SegmentExecutionState for seg 1
        state = SegmentExecutionState(index=1, state="pending")
        state = update_segment_execution_state(state, is_complete=False, total_segments=2)
        assert state.state == "active"
        assert state.index == 1

        # Step 4: Segment 1 completes (final)
        state = update_segment_execution_state(state, is_complete=True, total_segments=2)
        assert state.state == "complete"
        assert state.index == 1  # no further advancement
