from __future__ import annotations

from typing import Dict, Set

from src.core.types.subgoal import SubgoalLifecycleState
from src.core.planning.subgoals.transition_rules import SubgoalEvent

from src.core.planning.transitions.transition_types import TransitionError, TransitionResult
from src.core.planning.transitions.subgoal_table import (
    SUBGOAL_EVENT_TRANSITIONS,
    SUBGOAL_DIRECT_TRANSITIONS,
    SUBGOAL_EVENT_EXPLANATIONS,
    SUBGOAL_DIRECT_EXPLANATIONS,
    EVENT_TERMINAL_STATES,
    LIFECYCLE_TERMINAL_STATES,
)


class FullTransitionRules:
    """
    Complete governed, deterministic transition engine for Stratum-2 subgoal lifecycle.

    Covers two parallel, independent lifecycle views over SubgoalLifecycleState:
      - Execution lifecycle  (CREATED → … → SUCCESS / FAILED)
      - High-level lifecycle (PENDING → ACTIVE → SATISFIED / ABANDONED → CLOSED)

    The two lifecycles are NOT bridged.  FAILED is a shared terminal-recovery state.

    Two transition modes:
      apply_subgoal_transition  — event-driven, (state, event) → state
      apply_direct_transition   — state-only,   state → state (no event trigger)

    All methods are pure, deterministic, and have no side effects.
    """

    # ------------------------------------------------------------------
    # Event-driven transitions
    # ------------------------------------------------------------------

    def apply_subgoal_transition(
        self,
        current_state: SubgoalLifecycleState,
        event: SubgoalEvent,
    ) -> TransitionResult:
        """
        Apply an event to a subgoal lifecycle state.

        Returns TransitionResult:
          success=True  → to_state is the resulting state
          success=False → error describes why the transition is forbidden
        """
        from_val = current_state.value
        event_val = event.value

        if from_val in EVENT_TERMINAL_STATES:
            return TransitionResult(
                success=False,
                to_state=None,
                error=TransitionError(
                    from_state=from_val,
                    event=event_val,
                    reason=(
                        f"State {from_val!r} is event-terminal — "
                        "no outgoing event transitions are defined"
                    ),
                    allowed=False,
                ),
                explanation=f"{from_val!r} is event-terminal",
            )

        key = (from_val, event_val)
        to = SUBGOAL_EVENT_TRANSITIONS.get(key)

        if to is None:
            return TransitionResult(
                success=False,
                to_state=None,
                error=TransitionError(
                    from_state=from_val,
                    event=event_val,
                    reason=(
                        f"No event transition defined from {from_val!r} "
                        f"on event {event_val!r}"
                    ),
                    allowed=False,
                ),
                explanation=f"Forbidden: {from_val!r} + {event_val!r}",
            )

        explanation = SUBGOAL_EVENT_EXPLANATIONS.get(
            key, f"{from_val!r} + {event_val!r} → {to!r}"
        )
        return TransitionResult(success=True, to_state=to, error=None, explanation=explanation)

    # ------------------------------------------------------------------
    # Direct state transitions (no event trigger)
    # ------------------------------------------------------------------

    def apply_direct_transition(
        self,
        current_state: SubgoalLifecycleState,
        to_state: SubgoalLifecycleState,
    ) -> TransitionResult:
        """
        Apply a direct lifecycle state transition (e.g., SATISFIED → CLOSED).

        These transitions have no event trigger and are governed by
        LifecycleTransitionEngine semantics.
        """
        from_val = current_state.value
        to_val = to_state.value

        if from_val in LIFECYCLE_TERMINAL_STATES:
            return TransitionResult(
                success=False,
                to_state=None,
                error=TransitionError(
                    from_state=from_val,
                    event="[direct]",
                    reason=(
                        f"State {from_val!r} is lifecycle-terminal — "
                        "no outgoing transitions of any kind"
                    ),
                    allowed=False,
                ),
                explanation=f"{from_val!r} is lifecycle-terminal",
            )

        allowed: Set[str] = set(SUBGOAL_DIRECT_TRANSITIONS.get(from_val, frozenset()))
        if to_val not in allowed:
            return TransitionResult(
                success=False,
                to_state=None,
                error=TransitionError(
                    from_state=from_val,
                    event="[direct]",
                    reason=(
                        f"Direct transition from {from_val!r} to {to_val!r} "
                        "is not permitted"
                    ),
                    allowed=False,
                ),
                explanation=f"Forbidden direct: {from_val!r} → {to_val!r}",
            )

        explanation = SUBGOAL_DIRECT_EXPLANATIONS.get(
            (from_val, to_val), f"{from_val!r} → {to_val!r}"
        )
        return TransitionResult(success=True, to_state=to_val, error=None, explanation=explanation)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def explain_transition(self, from_state: str, event: str) -> str:
        """
        Return a deterministic explanation for an event-driven transition,
        or why it is forbidden.
        """
        key = (from_state, event)
        to = SUBGOAL_EVENT_TRANSITIONS.get(key)
        if to is not None:
            return SUBGOAL_EVENT_EXPLANATIONS.get(key, f"{from_state!r} + {event!r} → {to!r}")
        if from_state in EVENT_TERMINAL_STATES:
            return f"{from_state!r} is event-terminal — no outgoing event transitions"
        if from_state in LIFECYCLE_TERMINAL_STATES:
            return f"{from_state!r} is lifecycle-terminal — no transitions of any kind"
        return f"No event transition defined from {from_state!r} on event {event!r}"

    def explain_direct_transition(self, from_state: str, to_state: str) -> str:
        """
        Return a deterministic explanation for a direct state transition,
        or why it is forbidden.
        """
        if from_state in LIFECYCLE_TERMINAL_STATES:
            return f"{from_state!r} is lifecycle-terminal — no transitions of any kind"
        allowed = SUBGOAL_DIRECT_TRANSITIONS.get(from_state, frozenset())
        if to_state in allowed:
            return SUBGOAL_DIRECT_EXPLANATIONS.get(
                (from_state, to_state), f"{from_state!r} → {to_state!r}"
            )
        return f"Direct transition from {from_state!r} to {to_state!r} is not permitted"

    def list_allowed_transitions(self, current_state: str) -> Dict[str, str]:
        """
        Return {event_value: to_state_value} for all event-driven transitions
        available from current_state.  Returns {} for event-terminal states.
        """
        return {
            event: to
            for (state, event), to in SUBGOAL_EVENT_TRANSITIONS.items()
            if state == current_state
        }

    def list_direct_transitions(self, current_state: str) -> Set[str]:
        """
        Return the set of directly reachable state values from current_state
        (no event trigger required).
        """
        return set(SUBGOAL_DIRECT_TRANSITIONS.get(current_state, frozenset()))

    def is_event_terminal(self, state: str) -> bool:
        """True if no outgoing event transitions exist from this state."""
        return state in EVENT_TERMINAL_STATES

    def is_lifecycle_terminal(self, state: str) -> bool:
        """True if no outgoing transitions of any kind exist from this state."""
        return state in LIFECYCLE_TERMINAL_STATES
