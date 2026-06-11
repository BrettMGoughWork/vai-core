"""
Behaviour tests for the 2.3.7 execution-lifecycle transition engine.

Tests cover:
- All allowed transitions are accepted
- All disallowed transitions are rejected (exhaustive state-pair matrix)
- assert_allowed raises on illegal transitions
- Each event drives the correct next state
- Invalid events raise errors
- EVENT_TRANSITIONS consistency: every event-driven pair is in ALLOWED_TRANSITIONS
- Terminal and branching state shapes
"""
from __future__ import annotations

import itertools

import pytest

from src.strategy.types.subgoal import SubgoalLifecycleState
from src.strategy.planning.subgoals.transition_rules import ALLOWED_TRANSITIONS, SubgoalEvent
from src.strategy.planning.subgoals.transition_engine import TransitionEngine, _EVENT_TRANSITIONS
from src.strategy.planning.subgoals.errors import IllegalSubgoalTransitionError

_S = SubgoalLifecycleState
_E = SubgoalEvent

# The 9 explicitly required transitions
REQUIRED_TRANSITIONS = [
    (_S.CREATED,   _S.VALIDATED),
    (_S.VALIDATED, _S.READY),
    (_S.READY,     _S.RUNNING),
    (_S.RUNNING,   _S.SUCCESS),
    (_S.RUNNING,   _S.FAILED),
    (_S.RUNNING,   _S.BLOCKED),
    (_S.BLOCKED,   _S.READY),
    (_S.FAILED,    _S.RETRYING),
    (_S.RETRYING,  _S.RUNNING),
]

# The expected event→next-state table
REQUIRED_EVENT_TRANSITIONS = [
    (_S.CREATED,   _E.VALIDATE, _S.VALIDATED),
    (_S.VALIDATED, _E.ACTIVATE, _S.READY),
    (_S.READY,     _E.START,    _S.RUNNING),
    (_S.RUNNING,   _E.SUCCEED,  _S.SUCCESS),
    (_S.RUNNING,   _E.FAIL,     _S.FAILED),
    (_S.RUNNING,   _E.BLOCK,    _S.BLOCKED),
    (_S.BLOCKED,   _E.UNBLOCK,  _S.READY),
    (_S.FAILED,    _E.RETRY,    _S.RETRYING),
    (_S.RETRYING,  _E.RESUME,   _S.RUNNING),
]

# Only the execution-lifecycle states governed by this engine
EXECUTION_STATES = [
    _S.CREATED, _S.VALIDATED, _S.READY, _S.RUNNING,
    _S.SUCCESS, _S.FAILED, _S.BLOCKED, _S.RETRYING,
]


@pytest.fixture
def engine() -> TransitionEngine:
    return TransitionEngine()


# ---------------------------------------------------------------------------
# Transition table shape
# ---------------------------------------------------------------------------

class TestTransitionRules:
    def test_exactly_nine_allowed_transitions(self):
        execution_pairs = {
            pair for pair in ALLOWED_TRANSITIONS
            if pair[0] in EXECUTION_STATES and pair[1] in EXECUTION_STATES
        }
        assert len(execution_pairs) == 9

    def test_all_required_transitions_present(self):
        for pair in REQUIRED_TRANSITIONS:
            assert pair in ALLOWED_TRANSITIONS, f"Missing transition: {pair}"

    def test_all_transitions_have_non_empty_reason(self):
        for pair, reason in ALLOWED_TRANSITIONS.items():
            assert isinstance(reason, str) and reason.strip(), \
                f"Empty reason for {pair}"

    def test_no_self_transitions_in_execution_states(self):
        for state in EXECUTION_STATES:
            assert (state, state) not in ALLOWED_TRANSITIONS, \
                f"Self-transition found for {state}"


# ---------------------------------------------------------------------------
# is_allowed — exhaustive over execution state matrix
# ---------------------------------------------------------------------------

class TestIsAllowed:
    @pytest.mark.parametrize("from_s,to_s", REQUIRED_TRANSITIONS)
    def test_allowed_transitions_accepted(self, engine, from_s, to_s):
        assert engine.is_allowed(from_s, to_s) is True

    @pytest.mark.parametrize("from_s,to_s", [
        pair for pair in itertools.product(EXECUTION_STATES, EXECUTION_STATES)
        if pair not in REQUIRED_TRANSITIONS
    ])
    def test_disallowed_transitions_rejected(self, engine, from_s, to_s):
        assert engine.is_allowed(from_s, to_s) is False


# ---------------------------------------------------------------------------
# assert_allowed
# ---------------------------------------------------------------------------

class TestAssertAllowed:
    @pytest.mark.parametrize("from_s,to_s", REQUIRED_TRANSITIONS)
    def test_does_not_raise_for_valid_transition(self, engine, from_s, to_s):
        engine.assert_allowed(from_s, to_s)  # must not raise

    def test_raises_for_invalid_transition(self, engine):
        with pytest.raises(IllegalSubgoalTransitionError):
            engine.assert_allowed(_S.SUCCESS, _S.RUNNING)

    def test_error_message_contains_state_names(self, engine):
        with pytest.raises(IllegalSubgoalTransitionError, match="success"):
            engine.assert_allowed(_S.SUCCESS, _S.RUNNING)


# ---------------------------------------------------------------------------
# next_state — event-driven transitions
# ---------------------------------------------------------------------------

class TestNextState:
    @pytest.mark.parametrize("current,event,expected", REQUIRED_EVENT_TRANSITIONS)
    def test_event_produces_correct_next_state(self, engine, current, event, expected):
        assert engine.next_state(current, event) == expected

    def test_invalid_event_raises(self, engine):
        with pytest.raises(IllegalSubgoalTransitionError):
            engine.next_state(_S.SUCCESS, _E.START)

    def test_error_message_contains_state_and_event(self, engine):
        with pytest.raises(IllegalSubgoalTransitionError, match="success"):
            engine.next_state(_S.SUCCESS, _E.START)


# ---------------------------------------------------------------------------
# Consistency: event transitions must be a subset of allowed transitions
# ---------------------------------------------------------------------------

class TestConsistency:
    def test_every_event_transition_is_also_allowed(self, engine):
        for (state, event), next_s in _EVENT_TRANSITIONS.items():
            assert engine.is_allowed(state, next_s), \
                f"Event transition {state}+{event}→{next_s} not in ALLOWED_TRANSITIONS"

    def test_event_transition_count_matches_allowed_execution_count(self):
        assert len(_EVENT_TRANSITIONS) == 9


# ---------------------------------------------------------------------------
# State topology
# ---------------------------------------------------------------------------

class TestStateTopology:
    def test_success_is_terminal(self, engine):
        for to_s in EXECUTION_STATES:
            assert not engine.is_allowed(_S.SUCCESS, to_s), \
                f"SUCCESS should have no outgoing transitions, found one to {to_s}"

    def test_running_has_three_outgoing(self, engine):
        outgoing = [s for s in EXECUTION_STATES if engine.is_allowed(_S.RUNNING, s)]
        assert set(outgoing) == {_S.SUCCESS, _S.FAILED, _S.BLOCKED}

    def test_blocked_returns_only_to_ready(self, engine):
        outgoing = [s for s in EXECUTION_STATES if engine.is_allowed(_S.BLOCKED, s)]
        assert outgoing == [_S.READY]

    def test_failed_goes_only_to_retrying(self, engine):
        outgoing = [s for s in EXECUTION_STATES if engine.is_allowed(_S.FAILED, s)]
        assert outgoing == [_S.RETRYING]