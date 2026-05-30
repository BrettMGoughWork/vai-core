"""
Behaviour tests for Phase 2.5.2 — Full Transition Rules.

Coverage:
  - Event-driven transitions: valid paths, terminal-state rejection, forbidden pairs
  - Direct state transitions: valid paths, terminal-state rejection, forbidden pairs
  - Fallback / recovery paths (BLOCKED+FAIL, RETRYING+FAIL)
  - Drift-triggered path (RUNNING+BLOCK)
  - Repair-triggered path (FAILED+RETRY)
  - explain_transition / explain_direct_transition
  - list_allowed_transitions / list_direct_transitions
  - is_event_terminal / is_lifecycle_terminal
  - Table shape invariants
  - All (state, event) pairs not in the table are rejected
"""
from __future__ import annotations

import itertools

import pytest

from src.core.types.subgoal import SubgoalLifecycleState
from src.core.planning.subgoals.transition_rules import SubgoalEvent
from src.core.planning.transitions.full_transition_rules import FullTransitionRules
from src.core.planning.transitions.transition_types import TransitionError, TransitionResult
from src.core.planning.transitions.subgoal_table import (
    SUBGOAL_EVENT_TRANSITIONS,
    SUBGOAL_DIRECT_TRANSITIONS,
    EVENT_TERMINAL_STATES,
    LIFECYCLE_TERMINAL_STATES,
)

_S = SubgoalLifecycleState
_E = SubgoalEvent

ALL_STATES = list(_S)
ALL_EVENTS = list(_E)


@pytest.fixture
def engine() -> FullTransitionRules:
    return FullTransitionRules()


# ---------------------------------------------------------------------------
# Table shape invariants
# ---------------------------------------------------------------------------

class TestTableShape:
    def test_event_table_has_expected_size(self):
        # 11 execution + 3 high-level
        assert len(SUBGOAL_EVENT_TRANSITIONS) == 14

    def test_event_table_keys_are_valid_state_event_pairs(self):
        valid_states = {s.value for s in _S}
        valid_events = {e.value for e in _E}
        for (state, event), to in SUBGOAL_EVENT_TRANSITIONS.items():
            assert state in valid_states, f"Unknown from_state: {state!r}"
            assert event in valid_events, f"Unknown event: {event!r}"
            assert to in valid_states, f"Unknown to_state: {to!r}"

    def test_direct_table_covers_all_states(self):
        valid_states = {s.value for s in _S}
        assert set(SUBGOAL_DIRECT_TRANSITIONS.keys()) == valid_states

    def test_direct_table_successors_are_valid_states(self):
        valid_states = {s.value for s in _S}
        for state, successors in SUBGOAL_DIRECT_TRANSITIONS.items():
            for s in successors:
                assert s in valid_states, f"Unknown successor {s!r} from {state!r}"

    def test_no_self_loops_in_event_table(self):
        for (state, event), to in SUBGOAL_EVENT_TRANSITIONS.items():
            assert state != to, f"Self-loop detected: {state!r} + {event!r} → {to!r}"

    def test_no_self_loops_in_direct_table(self):
        for state, successors in SUBGOAL_DIRECT_TRANSITIONS.items():
            assert state not in successors, f"Self-loop in direct table: {state!r}"

    def test_lifecycle_terminal_subset_of_event_terminal(self):
        assert LIFECYCLE_TERMINAL_STATES.issubset(EVENT_TERMINAL_STATES)


# ---------------------------------------------------------------------------
# Event-driven: valid transitions
# ---------------------------------------------------------------------------

VALID_EVENT_CASES = [
    # Execution lifecycle
    (_S.CREATED,   _E.VALIDATE, "validated"),
    (_S.VALIDATED, _E.ACTIVATE, "ready"),
    (_S.READY,     _E.START,    "running"),
    (_S.RUNNING,   _E.SUCCEED,  "success"),
    (_S.RUNNING,   _E.FAIL,     "failed"),
    (_S.RUNNING,   _E.BLOCK,    "blocked"),
    (_S.BLOCKED,   _E.UNBLOCK,  "ready"),
    (_S.BLOCKED,   _E.FAIL,     "failed"),
    (_S.FAILED,    _E.RETRY,    "retrying"),
    (_S.RETRYING,  _E.RESUME,   "running"),
    (_S.RETRYING,  _E.FAIL,     "failed"),
    # High-level lifecycle
    (_S.PENDING,   _E.ACTIVATE, "active"),
    (_S.ACTIVE,    _E.SUCCEED,  "satisfied"),
    (_S.ACTIVE,    _E.FAIL,     "failed"),
]


class TestValidEventTransitions:
    @pytest.mark.parametrize("state,event,expected_to", VALID_EVENT_CASES)
    def test_valid_transition_succeeds(self, engine, state, event, expected_to):
        result = engine.apply_subgoal_transition(state, event)
        assert result.success is True
        assert result.to_state == expected_to
        assert result.error is None
        assert isinstance(result.explanation, str) and result.explanation

    @pytest.mark.parametrize("state,event,expected_to", VALID_EVENT_CASES)
    def test_valid_transition_returns_transition_result(self, engine, state, event, expected_to):
        result = engine.apply_subgoal_transition(state, event)
        assert isinstance(result, TransitionResult)


# ---------------------------------------------------------------------------
# Event-driven: terminal states
# ---------------------------------------------------------------------------

class TestEventTerminalStates:
    @pytest.mark.parametrize("terminal", [
        _S.SUCCESS, _S.SATISFIED, _S.ABANDONED, _S.CLOSED,
    ])
    @pytest.mark.parametrize("event", ALL_EVENTS)
    def test_event_terminal_state_rejects_all_events(self, engine, terminal, event):
        result = engine.apply_subgoal_transition(terminal, event)
        assert result.success is False
        assert result.to_state is None
        assert isinstance(result.error, TransitionError)
        assert result.error.from_state == terminal.value
        assert result.error.event == event.value
        assert result.error.allowed is False
        assert "terminal" in result.error.reason


# ---------------------------------------------------------------------------
# Event-driven: forbidden (state, event) pairs not in table
# ---------------------------------------------------------------------------

class TestForbiddenEventTransitions:
    @pytest.mark.parametrize("state,event", [
        (s, e) for s, e in itertools.product(ALL_STATES, ALL_EVENTS)
        if (s.value, e.value) not in SUBGOAL_EVENT_TRANSITIONS
        and s.value not in EVENT_TERMINAL_STATES
    ])
    def test_forbidden_pair_returns_failure(self, engine, state, event):
        result = engine.apply_subgoal_transition(state, event)
        assert result.success is False
        assert result.to_state is None
        assert isinstance(result.error, TransitionError)
        assert result.error.allowed is False


# ---------------------------------------------------------------------------
# Event-driven: semantic / named paths
# ---------------------------------------------------------------------------

class TestSemanticPaths:
    def test_drift_triggered_block(self, engine):
        """RUNNING + BLOCK → BLOCKED (drift-triggered)"""
        result = engine.apply_subgoal_transition(_S.RUNNING, _E.BLOCK)
        assert result.success is True
        assert result.to_state == "blocked"

    def test_repair_triggered_retry(self, engine):
        """FAILED + RETRY → RETRYING (repair-triggered)"""
        result = engine.apply_subgoal_transition(_S.FAILED, _E.RETRY)
        assert result.success is True
        assert result.to_state == "retrying"

    def test_unrecoverable_block_to_failed(self, engine):
        """BLOCKED + FAIL → FAILED (fallback)"""
        result = engine.apply_subgoal_transition(_S.BLOCKED, _E.FAIL)
        assert result.success is True
        assert result.to_state == "failed"

    def test_retry_exhausted_to_failed(self, engine):
        """RETRYING + FAIL → FAILED (retry exhausted fallback)"""
        result = engine.apply_subgoal_transition(_S.RETRYING, _E.FAIL)
        assert result.success is True
        assert result.to_state == "failed"

    def test_activate_is_state_relative(self, engine):
        """ACTIVATE serves two different lifecycles depending on from_state."""
        exec_result = engine.apply_subgoal_transition(_S.VALIDATED, _E.ACTIVATE)
        high_result = engine.apply_subgoal_transition(_S.PENDING, _E.ACTIVATE)
        assert exec_result.to_state == "ready"
        assert high_result.to_state == "active"

    def test_illegal_regression_from_success(self, engine):
        """SUCCESS + START should be rejected."""
        result = engine.apply_subgoal_transition(_S.SUCCESS, _E.START)
        assert result.success is False

    def test_illegal_regression_from_closed(self, engine):
        """CLOSED + VALIDATE should be rejected."""
        result = engine.apply_subgoal_transition(_S.CLOSED, _E.VALIDATE)
        assert result.success is False

    def test_cross_lifecycle_contamination_blocked(self, engine):
        """CREATED + SUCCEED must not bridge into high-level lifecycle."""
        result = engine.apply_subgoal_transition(_S.CREATED, _E.SUCCEED)
        assert result.success is False

    def test_abandoned_cannot_be_reached_via_event(self, engine):
        """ABANDONED has no inbound event path — only direct transitions lead there."""
        for state in ALL_STATES:
            for event in ALL_EVENTS:
                result = engine.apply_subgoal_transition(state, event)
                if result.success:
                    assert result.to_state != "abandoned", (
                        f"Unexpected event path to ABANDONED from {state.value!r} + {event.value!r}"
                    )


# ---------------------------------------------------------------------------
# Direct state transitions: valid paths
# ---------------------------------------------------------------------------

VALID_DIRECT_CASES = [
    (_S.PENDING,   _S.ACTIVE,     "active"),
    (_S.ACTIVE,    _S.SATISFIED,  "satisfied"),
    (_S.ACTIVE,    _S.FAILED,     "failed"),
    (_S.ACTIVE,    _S.ABANDONED,  "abandoned"),
    (_S.SATISFIED, _S.CLOSED,     "closed"),
    (_S.FAILED,    _S.CLOSED,     "closed"),
    (_S.ABANDONED, _S.CLOSED,     "closed"),
]


class TestValidDirectTransitions:
    @pytest.mark.parametrize("from_s,to_s,expected_val", VALID_DIRECT_CASES)
    def test_valid_direct_transition_succeeds(self, engine, from_s, to_s, expected_val):
        result = engine.apply_direct_transition(from_s, to_s)
        assert result.success is True
        assert result.to_state == expected_val
        assert result.error is None

    def test_abandoned_is_reachable_directly(self, engine):
        result = engine.apply_direct_transition(_S.ACTIVE, _S.ABANDONED)
        assert result.success is True
        assert result.to_state == "abandoned"

    def test_closed_is_reachable_from_all_terminal_non_lifecycle(self, engine):
        for state in [_S.SATISFIED, _S.FAILED, _S.ABANDONED]:
            result = engine.apply_direct_transition(state, _S.CLOSED)
            assert result.success is True, f"Expected CLOSED reachable from {state.value!r}"


# ---------------------------------------------------------------------------
# Direct state transitions: lifecycle-terminal
# ---------------------------------------------------------------------------

class TestDirectLifecycleTerminal:
    @pytest.mark.parametrize("to_s", ALL_STATES)
    def test_closed_is_lifecycle_terminal(self, engine, to_s):
        result = engine.apply_direct_transition(_S.CLOSED, to_s)
        assert result.success is False
        assert result.error is not None
        assert "lifecycle-terminal" in result.error.reason

    def test_direct_from_closed_has_no_event_field_confusion(self, engine):
        result = engine.apply_direct_transition(_S.CLOSED, _S.PENDING)
        assert result.error.event == "[direct]"


# ---------------------------------------------------------------------------
# Direct state transitions: forbidden pairs
# ---------------------------------------------------------------------------

class TestForbiddenDirectTransitions:
    def test_cannot_jump_from_pending_to_closed(self, engine):
        result = engine.apply_direct_transition(_S.PENDING, _S.CLOSED)
        assert result.success is False

    def test_cannot_jump_from_satisfied_to_active(self, engine):
        result = engine.apply_direct_transition(_S.SATISFIED, _S.ACTIVE)
        assert result.success is False

    def test_execution_states_have_no_direct_successors(self, engine):
        execution_only = [_S.CREATED, _S.VALIDATED, _S.READY, _S.RUNNING,
                          _S.SUCCESS, _S.BLOCKED, _S.RETRYING]
        for state in execution_only:
            for to_s in ALL_STATES:
                result = engine.apply_direct_transition(state, to_s)
                assert result.success is False, (
                    f"Unexpected direct transition from {state.value!r} to {to_s.value!r}"
                )


# ---------------------------------------------------------------------------
# explain_transition
# ---------------------------------------------------------------------------

class TestExplainTransition:
    def test_valid_transition_returns_non_empty_string(self, engine):
        msg = engine.explain_transition("running", "succeed")
        assert isinstance(msg, str) and msg

    def test_forbidden_transition_returns_reason(self, engine):
        msg = engine.explain_transition("success", "start")
        assert "terminal" in msg or "forbidden" in msg.lower() or "No event" in msg

    def test_event_terminal_state_explains_terminality(self, engine):
        msg = engine.explain_transition("success", "start")
        assert "terminal" in msg

    def test_unknown_pair_explains_missing_rule(self, engine):
        msg = engine.explain_transition("created", "succeed")
        assert "No event transition" in msg or "Forbidden" in msg or "forbidden" in msg.lower()

    @pytest.mark.parametrize("state_val,event_val,to_val", [
        (s, e, SUBGOAL_EVENT_TRANSITIONS[(s, e)])
        for (s, e) in SUBGOAL_EVENT_TRANSITIONS
    ])
    def test_all_valid_pairs_have_non_empty_explanation(self, engine, state_val, event_val, to_val):
        msg = engine.explain_transition(state_val, event_val)
        assert isinstance(msg, str) and msg


# ---------------------------------------------------------------------------
# explain_direct_transition
# ---------------------------------------------------------------------------

class TestExplainDirectTransition:
    def test_valid_direct_returns_explanation(self, engine):
        msg = engine.explain_direct_transition("active", "satisfied")
        assert isinstance(msg, str) and msg

    def test_forbidden_direct_returns_reason(self, engine):
        msg = engine.explain_direct_transition("pending", "closed")
        assert "not permitted" in msg or "Forbidden" in msg or "forbidden" in msg.lower()

    def test_lifecycle_terminal_direct_explains(self, engine):
        msg = engine.explain_direct_transition("closed", "pending")
        assert "lifecycle-terminal" in msg


# ---------------------------------------------------------------------------
# list_allowed_transitions
# ---------------------------------------------------------------------------

class TestListAllowedTransitions:
    def test_running_has_three_event_transitions(self, engine):
        allowed = engine.list_allowed_transitions("running")
        assert set(allowed.keys()) == {"succeed", "fail", "block"}

    def test_blocked_has_two_event_transitions(self, engine):
        allowed = engine.list_allowed_transitions("blocked")
        assert set(allowed.keys()) == {"unblock", "fail"}

    def test_failed_has_one_event_transition(self, engine):
        allowed = engine.list_allowed_transitions("failed")
        assert set(allowed.keys()) == {"retry"}

    def test_retrying_has_two_event_transitions(self, engine):
        allowed = engine.list_allowed_transitions("retrying")
        assert set(allowed.keys()) == {"resume", "fail"}

    def test_success_returns_empty(self, engine):
        assert engine.list_allowed_transitions("success") == {}

    def test_satisfied_returns_empty(self, engine):
        assert engine.list_allowed_transitions("satisfied") == {}

    def test_closed_returns_empty(self, engine):
        assert engine.list_allowed_transitions("closed") == {}

    def test_abandoned_returns_empty(self, engine):
        assert engine.list_allowed_transitions("abandoned") == {}

    def test_created_has_one_event(self, engine):
        allowed = engine.list_allowed_transitions("created")
        assert set(allowed.keys()) == {"validate"}

    def test_pending_has_one_event(self, engine):
        allowed = engine.list_allowed_transitions("pending")
        assert set(allowed.keys()) == {"activate"}

    def test_active_has_two_events(self, engine):
        allowed = engine.list_allowed_transitions("active")
        assert set(allowed.keys()) == {"succeed", "fail"}


# ---------------------------------------------------------------------------
# list_direct_transitions
# ---------------------------------------------------------------------------

class TestListDirectTransitions:
    def test_active_has_three_direct_successors(self, engine):
        direct = engine.list_direct_transitions("active")
        assert direct == {"satisfied", "failed", "abandoned"}

    def test_satisfied_goes_only_to_closed(self, engine):
        assert engine.list_direct_transitions("satisfied") == {"closed"}

    def test_closed_has_no_direct_successors(self, engine):
        assert engine.list_direct_transitions("closed") == set()

    def test_running_has_no_direct_successors(self, engine):
        assert engine.list_direct_transitions("running") == set()

    def test_pending_goes_only_to_active(self, engine):
        assert engine.list_direct_transitions("pending") == {"active"}


# ---------------------------------------------------------------------------
# is_event_terminal / is_lifecycle_terminal
# ---------------------------------------------------------------------------

class TestTerminalPredicates:
    @pytest.mark.parametrize("state,expected", [
        (_S.SUCCESS,   True),
        (_S.SATISFIED, True),
        (_S.ABANDONED, True),
        (_S.CLOSED,    True),
        (_S.RUNNING,   False),
        (_S.FAILED,    False),   # FAILED has RETRY event
        (_S.BLOCKED,   False),
        (_S.RETRYING,  False),
        (_S.CREATED,   False),
        (_S.PENDING,   False),
        (_S.ACTIVE,    False),
        (_S.VALIDATED, False),
        (_S.READY,     False),
    ])
    def test_is_event_terminal(self, engine, state, expected):
        assert engine.is_event_terminal(state.value) is expected

    @pytest.mark.parametrize("state,expected", [
        (_S.CLOSED,    True),
        (_S.SUCCESS,   False),   # success has no events, but DIRECT table has no successors either
        (_S.SATISFIED, False),   # satisfied → closed is a direct transition
        (_S.ABANDONED, False),   # abandoned → closed is a direct transition
        (_S.FAILED,    False),   # failed → closed is a direct transition
        (_S.RUNNING,   False),
    ])
    def test_is_lifecycle_terminal(self, engine, state, expected):
        assert engine.is_lifecycle_terminal(state.value) is expected

    def test_lifecycle_terminal_implies_event_terminal(self, engine):
        for state in ALL_STATES:
            if engine.is_lifecycle_terminal(state.value):
                assert engine.is_event_terminal(state.value), (
                    f"{state.value!r} is lifecycle-terminal but not event-terminal"
                )


# ---------------------------------------------------------------------------
# TransitionError / TransitionResult structure
# ---------------------------------------------------------------------------

class TestResultStructure:
    def test_failure_result_has_none_to_state(self, engine):
        result = engine.apply_subgoal_transition(_S.SUCCESS, _E.START)
        assert result.to_state is None

    def test_success_result_has_none_error(self, engine):
        result = engine.apply_subgoal_transition(_S.READY, _E.START)
        assert result.error is None

    def test_transition_error_allowed_is_false(self, engine):
        result = engine.apply_subgoal_transition(_S.SUCCESS, _E.START)
        assert result.error.allowed is False

    def test_transition_error_carries_from_and_event(self, engine):
        result = engine.apply_subgoal_transition(_S.SUCCESS, _E.VALIDATE)
        assert result.error.from_state == "success"
        assert result.error.event == "validate"

    def test_direct_failure_event_field_is_direct_marker(self, engine):
        result = engine.apply_direct_transition(_S.CLOSED, _S.PENDING)
        assert result.error.event == "[direct]"
