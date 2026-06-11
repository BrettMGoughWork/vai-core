from __future__ import annotations

from src.strategy.types.subgoal import Subgoal
from src.strategy.planning.subgoals.validation_engine import ValidationEngine


class SubgoalValidator:
    """
    Thin wrapper around ValidationEngine for SubgoalManager compatibility.

    Responsibilities:
    - Provide a stable, minimal interface for SubgoalManager
    - Ensure validator returns a deterministic boolean
    - Prevent accidental leakage of exceptions or non-boolean values
    """

    def __init__(self):
        self._validator = ValidationEngine()

    def validate(self, subgoal: Subgoal) -> bool:
        """
        Returns True if the subgoal is structurally valid.
        Returns False if validation fails.

        The manager decides how to handle failures.
        """
        try:
            errors = self._validator.validate(subgoal)
            return len(errors) == 0
        except Exception:
            # Manager will raise InvalidSubgoalError
            return False