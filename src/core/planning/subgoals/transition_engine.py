from __future__ import annotations

from typing import Dict, Tuple

from src.core.types.subgoal import SubgoalLifecycleState
from src.core.planning.subgoals.transition_rules import (
    ALLOWED_TRANSITIONS,
    SubgoalEvent,
)
from src.core.planning.subgoals.errors import IllegalSubgoalTransitionError


_S = SubgoalLifecycleState
_E = SubgoalEvent

# Maps (current_state, event) -> next_state.
# Every entry here must correspond to a pair in ALLOWED_TRANSITIONS.
_EVENT_TRANSITIONS: Dict[Tuple[SubgoalLifecycleState, SubgoalEvent], SubgoalLifecycleState] = {
    (_S.CREATED,   _E.VALIDATE): _S.VALIDATED,
    (_S.VALIDATED, _E.ACTIVATE): _S.READY,
    (_S.READY,     _E.START):    _S.RUNNING,
    (_S.RUNNING,   _E.SUCCEED):  _S.SUCCESS,
    (_S.RUNNING,   _E.FAIL):     _S.FAILED,
    (_S.RUNNING,   _E.BLOCK):    _S.BLOCKED,
    (_S.BLOCKED,   _E.UNBLOCK):  _S.READY,
    (_S.FAILED,    _E.RETRY):    _S.RETRYING,
    (_S.RETRYING,  _E.RESUME):   _S.RUNNING,
}


class TransitionEngine:
    """
    Pure deterministic execution-lifecycle transition engine.

    Uses only the transition table from transition_rules.py.
    No state, no side effects, no heuristics, no LLM calls.
    """

    def is_allowed(
        self,
        from_state: SubgoalLifecycleState,
        to_state: SubgoalLifecycleState,
    ) -> bool:
        return (from_state, to_state) in ALLOWED_TRANSITIONS

    def assert_allowed(
        self,
        from_state: SubgoalLifecycleState,
        to_state: SubgoalLifecycleState,
    ) -> None:
        if not self.is_allowed(from_state, to_state):
            raise IllegalSubgoalTransitionError(
                f"Transition {from_state.value!r} → {to_state.value!r} is not allowed"
            )

    def next_state(
        self,
        current: SubgoalLifecycleState,
        event: SubgoalEvent,
    ) -> SubgoalLifecycleState:
        result = _EVENT_TRANSITIONS.get((current, event))
        if result is None:
            raise IllegalSubgoalTransitionError(
                f"No transition from {current.value!r} on event {event.value!r}"
            )
        return result
