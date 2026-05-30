from __future__ import annotations

from typing import Optional, Dict, List

from src.core.types.subgoal import Subgoal, SubgoalLifecycleState
from src.core.planning.validators.subgoal_validator import SubgoalValidator
from .transitions import LifecycleTransitionEngine
from .state import SubgoalState
from .errors import (
    SubgoalNotFoundError,
    InvalidSubgoalError,
    IllegalSubgoalTransitionError,
    SubgoalHierarchyError,
)
from .events import (
    SubgoalCreatedEvent,
    SubgoalTransitionEvent,
)


class SubgoalManager:
    """
    Deterministic governance layer for subgoal creation, validation,
    lifecycle transitions, and hierarchy enforcement.
    """

    def __init__(self, state: SubgoalState, validator: SubgoalValidator):
        self._state = state
        self._validator = validator
        self._transitions = LifecycleTransitionEngine()

    # ------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------
    def create_subgoal(
        self,
        goal: str,
        context: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
        parent_id: Optional[str] = None,
    ) -> Subgoal:
        parent = None
        if parent_id:
            parent = self._state.get(parent_id)
            if parent is None:
                raise SubgoalHierarchyError(f"Parent subgoal {parent_id} not found")

        subgoal = Subgoal.new(
            goal=goal,
            context=context or {},
            metadata=metadata or {},
            parent_id=parent_id,
        )

        # Validate before insertion
        self.validate_subgoal(subgoal)

        # Insert into state
        self._state.insert(subgoal)

        # Emit event
        event = SubgoalCreatedEvent.from_subgoal(subgoal)
        self._state.record_event(event)

        return subgoal

    # ------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------
    def validate_subgoal(self, subgoal: Subgoal) -> None:
        if not self._validator.validate(subgoal):
            raise InvalidSubgoalError(f"Subgoal {subgoal.id} failed validation")

        # Hierarchy invariants
        if subgoal.parent_id:
            parent = self._state.get(subgoal.parent_id)
            if parent is None:
                raise SubgoalHierarchyError(
                    f"Parent {subgoal.parent_id} does not exist"
                )

    # ------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------
    def transition(
        self,
        subgoal_id: str,
        new_state: SubgoalLifecycleState,
    ) -> Subgoal:
        subgoal = self._state.get(subgoal_id)
        if subgoal is None:
            raise SubgoalNotFoundError(subgoal_id)

        # Validate transition legality
        if not self._transitions.is_legal(subgoal.state, new_state):
            raise IllegalSubgoalTransitionError(
                f"{subgoal.state} → {new_state} is not allowed"
            )

        # Apply transition
        updated = subgoal.with_state(new_state)

        # Validate updated subgoal
        self.validate_subgoal(updated)

        # Persist
        self._state.update(updated)

        # Emit event
        event = SubgoalTransitionEvent.from_transition(
            old=subgoal,
            new=updated,
        )
        self._state.record_event(event)

        return updated

    # ------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------
    def get(self, subgoal_id: str) -> Optional[Subgoal]:
        return self._state.get(subgoal_id)

    def list_children(self, parent_id: str) -> List[Subgoal]:
        return self._state.list_children(parent_id)

    def list_active_chain(self) -> List[Subgoal]:
        """
        Returns the chain of active subgoals from root → leaf.
        """
        return self._state.active_chain()