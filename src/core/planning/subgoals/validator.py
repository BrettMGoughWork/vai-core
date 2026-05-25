from __future__ import annotations

from typing import Any

from .model import Subgoal
from src.core.planning.validators.subgoal_validator import SubgoalValidator as _CoreSubgoalValidator


class SubgoalValidator:
    """
    Thin wrapper around the core SubgoalValidator defined in 2.3.1.

    Responsibilities:
    - Provide a stable, minimal interface for SubgoalManager
    - Ensure validator returns a deterministic boolean
    - Prevent accidental leakage of exceptions or non-boolean values
    """

    def __init__(self):
        self._validator = _CoreSubgoalValidator()

    def validate(self, subgoal: Subgoal) -> bool:
        """
        Returns True if the subgoal is structurally valid.
        Returns False if validation fails.

        The manager decides how to handle failures.
        """
        try:
            result = self._validator.validate(subgoal)
            return bool(result)
        except Exception:
            # Manager will raise InvalidSubgoalError
            return False