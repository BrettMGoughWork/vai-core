from __future__ import annotations

from typing import Dict, List, Optional

from .model import Subgoal
from .errors import SubgoalNotFoundError


class SubgoalState:
    """
    Deterministic in-memory store for subgoals and their events.

    This is a Stratum‑2 state container:
    - No side effects
    - No planner logic
    - No lifecycle rules (handled by manager + transition engine)
    - Pure JSON-serialisable structures
    """

    def __init__(self):
        # subgoal_id -> Subgoal
        self._subgoals: Dict[str, Subgoal] = {}

        # chronological event log (pure JSON)
        self._events: List[dict] = []

    # ------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------
    def insert(self, subgoal: Subgoal) -> None:
        self._subgoals[subgoal.subgoal_id] = subgoal

    def update(self, subgoal: Subgoal) -> None:
        if subgoal.subgoal_id not in self._subgoals:
            raise SubgoalNotFoundError(subgoal.subgoal_id)
        self._subgoals[subgoal.subgoal_id] = subgoal

    def get(self, subgoal_id: str) -> Optional[Subgoal]:
        return self._subgoals.get(subgoal_id)

    # ------------------------------------------------------------
    # Hierarchy helpers
    # ------------------------------------------------------------
    def list_children(self, parent_id: str) -> List[Subgoal]:
        return [
            sg for sg in self._subgoals.values()
            if sg.parent_id == parent_id
        ]

    def active_chain(self) -> List[Subgoal]:
        """
        Returns the chain of active subgoals from root → leaf.

        Definition:
        - A root subgoal is one with no parent_id.
        - The active chain is the deepest path where each subgoal is ACTIVE.
        """
        # Find all roots
        roots = [sg for sg in self._subgoals.values() if sg.parent_id is None]
        if not roots:
            return []

        # There should only be one active root at a time
        active_roots = [sg for sg in roots if sg.state.value == "active"]
        if not active_roots:
            return []

        chain = []
        current = active_roots[0]

        while current:
            chain.append(current)
            children = self.list_children(current.subgoal_id)
            active_children = [c for c in children if c.state.value == "active"]

            if not active_children:
                break

            # Deterministic: if multiple active children exist, choose lexicographically
            active_children.sort(key=lambda sg: sg.subgoal_id)
            current = active_children[0]

        return chain

    # ------------------------------------------------------------
    # Event log
    # ------------------------------------------------------------
    def record_event(self, event: dict) -> None:
        """
        Events must be JSON-pure dicts.
        """
        self._events.append(event)

    def events(self) -> List[dict]:
        return list(self._events)