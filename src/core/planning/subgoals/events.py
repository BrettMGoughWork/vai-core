from __future__ import annotations

from typing import Dict, Any

from .model import Subgoal, SubgoalLifecycleState


class SubgoalCreatedEvent:
    """
    Pure JSON event emitted when a subgoal is created.
    """

    @staticmethod
    def from_subgoal(subgoal: Subgoal) -> Dict[str, Any]:
        return {
            "type": "subgoal_created",
            "subgoal_id": subgoal.subgoal_id,
            "goal": subgoal.goal,
            "parent_id": subgoal.parent_id,
            "state": subgoal.state.value,
            "context": subgoal.context,
            "metadata": subgoal.metadata,
            "created_at": subgoal.created_at,
            "canonical_hash": subgoal.canonical_hash,
        }


class SubgoalTransitionEvent:
    """
    Pure JSON event emitted when a subgoal transitions lifecycle state.
    """

    @staticmethod
    def from_transition(old: Subgoal, new: Subgoal) -> Dict[str, Any]:
        return {
            "type": "subgoal_transition",
            "subgoal_id": new.subgoal_id,
            "from_state": old.state.value,
            "to_state": new.state.value,
            "goal": new.goal,
            "parent_id": new.parent_id,
            "context": new.context,
            "metadata": new.metadata,
            "created_at": new.created_at,
            "canonical_hash": new.canonical_hash,
        }