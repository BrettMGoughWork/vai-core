from __future__ import annotations
from typing import Dict, Set
from src.core.types.subgoal import SubgoalLifecycleState

class LifecycleTransitionEngine:
    """
    Pure deterministic transition legality engine.

    This component defines the allowed lifecycle transitions for subgoals.
    It contains no state, no side effects, and no references to planner logic.
    """

    # ------------------------------------------------------------
    # Legal transition table
    # ------------------------------------------------------------
    _LEGAL_TRANSITIONS: Dict[SubgoalLifecycleState, Set[SubgoalLifecycleState]] = {
        SubgoalLifecycleState.PENDING: {
            SubgoalLifecycleState.ACTIVE,
        },

        SubgoalLifecycleState.ACTIVE: {
            SubgoalLifecycleState.SATISFIED,
            SubgoalLifecycleState.FAILED,
            SubgoalLifecycleState.ABANDONED,
        },

        SubgoalLifecycleState.SATISFIED: {
            SubgoalLifecycleState.CLOSED,
        },

        SubgoalLifecycleState.FAILED: {
            SubgoalLifecycleState.CLOSED,
        },

        SubgoalLifecycleState.ABANDONED: {
            SubgoalLifecycleState.CLOSED,
        },

        # Terminal state: no outgoing transitions
        SubgoalLifecycleState.CLOSED: set(),
    }

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------
    def is_legal(
        self,
        current: SubgoalLifecycleState,
        new: SubgoalLifecycleState,
    ) -> bool:
        """
        Returns True if the transition current → new is allowed.
        """
        allowed = self._LEGAL_TRANSITIONS.get(current)
        if allowed is None:
            return False
        return new in allowed

    def legal_transitions(
        self,
        current: SubgoalLifecycleState,
    ) -> Set[SubgoalLifecycleState]:
        """
        Returns the set of legal next states for the given current state.
        """
        return self._LEGAL_TRANSITIONS.get(current, set())