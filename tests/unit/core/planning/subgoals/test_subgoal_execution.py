from __future__ import annotations

import copy
import json

import pytest

from src.core.planning.subgoals.execution import (
    SubgoalExecutionPhase,
    SubgoalExecutionState,
    transition_subgoal_state,
    advance_subgoal_index,
    update_subgoal_execution_state,
    subgoal_progress_summary,
    subgoal_completion_summary,
    is_agent_complete,
)


# ──────────────────────────────────────────────────────────────────────────────
# SubgoalExecutionPhase Enum
# ──────────────────────────────────────────────────────────────────────────────

class TestSubgoalExecutionPhaseEnum:
    """The enum must define exactly PENDING, ACTIVE, COMPLETE."""

    def test_values(self):
        assert SubgoalExecutionPhase.PENDING == "pending"
        assert SubgoalExecutionPhase.ACTIVE == "active"
        assert SubgoalExecutionPhase.COMPLETE == "complete"

    def test_is_string_enum(self):
        assert isinstance(SubgoalExecutionPhase.PENDING, str)
        assert issubclass(SubgoalExecutionPhase, str)


# ──────────────────────────────────────────────────────────────────────────────
# transition_subgoal_state
# ──────────────────────────────────────────────────────────────────────────────

class TestTransitionSubgoalState:
    """Deterministic state machine: pending → active → complete."""

    def test_pending_to_active(self):
        assert transition_subgoal_state("pending", False) == "active"
        assert transition_subgoal_state("pending", True) == "active"

    def test_active_stays_active(self):
        assert transition_subgoal_state("active", False) == "active"

    def test_active_to_complete(self):
        assert transition_subgoal_state("active", True) == "complete"

    def test_complete_stays_complete(self):
        assert transition_subgoal_state("complete", False) == "complete"
        assert transition_subgoal_state("complete", True) == "complete"

    def test_deterministic(self):
        """Same inputs must always produce same output."""
        for state in ("pending", "active", "complete"):
            for is_complete in (True, False):
                a = transition_subgoal_state(state, is_complete)
                b = transition_subgoal_state(copy.deepcopy(state), is_complete)
                assert a == b

    def test_invalid_state_raises(self):
        with pytest.raises(ValueError, match="Invalid subgoal state"):
            transition_subgoal_state("invalid", False)
        with pytest.raises(ValueError, match="Invalid subgoal state"):
            transition_subgoal_state("", False)
        with pytest.raises(ValueError, match="Invalid subgoal state"):
            transition_subgoal_state(None, False)

    def test_pure_no_mutation(self):
        """Function must not mutate its inputs."""
        state = "pending"
        saved = state
        transition_subgoal_state(state, True)
        assert state == saved

    def test_result_is_valid_enum(self):
        """All valid transitions must return valid SubgoalExecutionPhase values."""
        for state in ("pending", "active", "complete"):
            for is_complete in (True, False):
                result = transition_subgoal_state(state, is_complete)
                assert result in (
                    SubgoalExecutionPhase.PENDING,
                    SubgoalExecutionPhase.ACTIVE,
                    SubgoalExecutionPhase.COMPLETE,
                )
                assert isinstance(result, str)


# ──────────────────────────────────────────────────────────────────────────────
# advance_subgoal_index
# ──────────────────────────────────────────────────────────────────────────────

class TestAdvanceSubgoalIndex:
    """Pure index advancement with clamping."""

    def test_advance_from_zero(self):
        assert advance_subgoal_index(0, 3) == 1
        assert advance_subgoal_index(0, 2) == 1

    def test_advance_mid_execution(self):
        assert advance_subgoal_index(1, 3) == 2

    def test_no_advance_at_final(self):
        """At the final subgoal, stay at current index."""
        assert advance_subgoal_index(2, 3) == 2
        assert advance_subgoal_index(3, 3) == 3

    def test_single_subgoal(self):
        """Single-subgoal execution: index stays at 0."""
        assert advance_subgoal_index(0, 1) == 0

    def test_zero_subgoals(self):
        """Zero subgoals: index unchanged."""
        assert advance_subgoal_index(0, 0) == 0
        assert advance_subgoal_index(5, 0) == 5

    def test_negative_index_raises(self):
        with pytest.raises(ValueError, match="current_index must be >= 0"):
            advance_subgoal_index(-1, 3)

    def test_negative_total_raises(self):
        with pytest.raises(ValueError, match="total_subgoals must be >= 0"):
            advance_subgoal_index(0, -1)

    def test_deterministic(self):
        for idx in range(5):
            for total in range(5):
                a = advance_subgoal_index(idx, total)
                b = advance_subgoal_index(idx, total)
                assert a == b

    def test_pure_no_mutation(self):
        idx = 2
        total = 5
        saved_idx = idx
        saved_total = total
        advance_subgoal_index(idx, total)
        assert idx == saved_idx
        assert total == saved_total


# ──────────────────────────────────────────────────────────────────────────────
# update_subgoal_execution_state
# ──────────────────────────────────────────────────────────────────────────────

class TestUpdateSubgoalExecutionState:
    """Wrapper function combining transition + index advancement."""

    def test_pending_to_active_preserves_index(self):
        state = SubgoalExecutionState(index=0, state="pending")
        result = update_subgoal_execution_state(state, is_complete=False, total_subgoals=3)
        assert result.state == "active"
        assert result.index == 0

    def test_active_to_complete_advances_index(self):
        state = SubgoalExecutionState(index=0, state="active")
        result = update_subgoal_execution_state(state, is_complete=True, total_subgoals=3)
        assert result.state == "complete"
        assert result.index == 1

    def test_complete_stays_complete(self):
        state = SubgoalExecutionState(index=1, state="complete")
        result = update_subgoal_execution_state(state, is_complete=True, total_subgoals=3)
        assert result.state == "complete"
        assert result.index == 1  # no further advancement

    def test_final_subgoal_no_advancement(self):
        """Completing the final subgoal: index advances past total_subgoals
        so the caller can distinguish 'final subgoal actually completed'
        from 'previous subgoal advanced to the final index'."""
        state = SubgoalExecutionState(index=2, state="active")
        result = update_subgoal_execution_state(state, is_complete=True, total_subgoals=3)
        assert result.state == "complete"
        assert result.index == 3  # past-the-end sentinel

    def test_returns_new_instance(self):
        """Must return a new SubgoalExecutionState, not mutate input."""
        state = SubgoalExecutionState(index=0, state="pending")
        result = update_subgoal_execution_state(state, is_complete=True, total_subgoals=3)
        assert result is not state
        assert state.state == "pending"
        assert state.index == 0

    def test_deterministic(self):
        state = SubgoalExecutionState(index=1, state="active")
        r1 = update_subgoal_execution_state(state, True, 4)
        r2 = update_subgoal_execution_state(
            SubgoalExecutionState(index=1, state="active"), True, 4
        )
        assert r1 == r2

    def test_invalid_state_raises(self):
        state = SubgoalExecutionState(index=0, state="invalid")
        with pytest.raises(ValueError):
            update_subgoal_execution_state(state, True, 3)

    def test_negative_index_raises(self):
        state = SubgoalExecutionState(index=-1, state="pending")
        with pytest.raises(ValueError):
            update_subgoal_execution_state(state, True, 3)

    def test_immutable_result(self):
        """SubgoalExecutionState is frozen — cannot mutate after creation."""
        result = update_subgoal_execution_state(
            SubgoalExecutionState(index=0, state="pending"),
            True,
            3,
        )
        with pytest.raises(Exception):
            result.state = "pending"  # frozen dataclass


# ──────────────────────────────────────────────────────────────────────────────
# is_agent_complete
# ──────────────────────────────────────────────────────────────────────────────

class TestIsAgentComplete:
    """Agent completion detection."""

    def test_not_complete_when_pending(self):
        state = SubgoalExecutionState(index=0, state="pending")
        assert is_agent_complete(state, 3) is False

    def test_not_complete_when_active(self):
        state = SubgoalExecutionState(index=0, state="active")
        assert is_agent_complete(state, 3) is False

    def test_not_complete_when_complete_but_not_final(self):
        """Complete at index 0 of 3 subgoals → agent is not done."""
        state = SubgoalExecutionState(index=0, state="complete")
        assert is_agent_complete(state, 3) is False

    def test_complete_when_complete_at_final(self):
        """Complete at index 2 of 3 subgoals → agent is done."""
        state = SubgoalExecutionState(index=2, state="complete")
        assert is_agent_complete(state, 3) is True

    def test_complete_single_subgoal(self):
        """Single subgoal complete → agent is done."""
        state = SubgoalExecutionState(index=0, state="complete")
        assert is_agent_complete(state, 1) is True

    def test_zero_subgoals_complete(self):
        """Zero subgoals → trivially complete."""
        state = SubgoalExecutionState(index=0, state="pending")
        assert is_agent_complete(state, 0) is True

    def test_negative_total_complete(self):
        """Negative total → trivially complete."""
        state = SubgoalExecutionState(index=0, state="pending")
        assert is_agent_complete(state, -1) is True

    def test_deterministic(self):
        state = SubgoalExecutionState(index=2, state="complete")
        a = is_agent_complete(state, 3)
        b = is_agent_complete(SubgoalExecutionState(index=2, state="complete"), 3)
        assert a == b


# ──────────────────────────────────────────────────────────────────────────────
# Structural Summary Hooks
# ──────────────────────────────────────────────────────────────────────────────

class TestStructuralSummaryHooks:
    """Placeholder hooks for Phase 2.12.2 — must be JSON-safe."""

    def test_progress_summary_keys(self):
        state = SubgoalExecutionState(index=0, state="active")
        summary = subgoal_progress_summary(state)
        assert summary == {"index": 0, "state": "active"}

    def test_completion_summary_keys(self):
        state = SubgoalExecutionState(index=2, state="complete")
        summary = subgoal_completion_summary(state)
        assert summary == {"is_complete": True}

        active = SubgoalExecutionState(index=0, state="active")
        assert subgoal_completion_summary(active) == {"is_complete": False}

    def test_summaries_are_json_safe(self):
        state = SubgoalExecutionState(index=0, state="active")
        json.dumps(subgoal_progress_summary(state))
        json.dumps(subgoal_completion_summary(state))

    def test_summaries_do_not_mutate_input(self):
        state = SubgoalExecutionState(index=1, state="active")
        saved = copy.deepcopy(state)
        subgoal_progress_summary(state)
        subgoal_completion_summary(state)
        assert state == saved


# ──────────────────────────────────────────────────────────────────────────────
# Edge Cases
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Boundary and edge-case scenarios."""

    def test_zero_subgoals_transition(self):
        """Transitions are valid even with zero total subgoals."""
        state = SubgoalExecutionState(index=0, state="pending")
        result = update_subgoal_execution_state(state, True, 0)
        assert result.state == "active"  # pending → active
        assert result.index == 0  # no advancement (0 subgoals)

    def test_zero_subgoals_complete(self):
        """Active subgoal completes with zero total."""
        state = SubgoalExecutionState(index=0, state="active")
        result = update_subgoal_execution_state(state, True, 0)
        assert result.state == "complete"
        assert result.index == 0

    def test_large_subgoal_count(self):
        """Large total_subgoals should not break."""
        state = SubgoalExecutionState(index=9998, state="active")
        result = update_subgoal_execution_state(state, True, 10000)
        assert result.state == "complete"
        assert result.index == 9999

    def test_default_execution_state(self):
        """Default SubgoalExecutionState starts at index 0, pending."""
        state = SubgoalExecutionState()
        assert state.index == 0
        assert state.state == "pending"

    def test_full_lifecycle(self):
        """Complete lifecycle: pending → active → complete across subgoals."""
        state = SubgoalExecutionState()

        # Step 1: Start execution
        state = update_subgoal_execution_state(state, is_complete=False, total_subgoals=2)
        assert state.state == "active"
        assert state.index == 0

        # Step 2: Subgoal 0 completes
        state = update_subgoal_execution_state(state, is_complete=True, total_subgoals=2)
        assert state.state == "complete"
        assert state.index == 1

        # Step 3: Next subgoal starts
        state = SubgoalExecutionState(index=1, state="pending")
        state = update_subgoal_execution_state(state, is_complete=False, total_subgoals=2)
        assert state.state == "active"
        assert state.index == 1

        # Step 4: Subgoal 1 completes (final) — agent complete
        state = update_subgoal_execution_state(state, is_complete=True, total_subgoals=2)
        assert state.state == "complete"
        assert state.index == 2  # past-the-end sentinel when final subgoal completes
        assert is_agent_complete(state, 2) is True
