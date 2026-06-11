from __future__ import annotations

from typing import List

from src.strategy.types.subgoal import Subgoal
from src.strategy.planning.subgoals.validation_errors import ValidationError
from src.strategy.planning.subgoals.validation_rules import (
    validate_id_present,
    validate_goal_present,
    validate_parent_consistency,
    validate_state_allowed,
    validate_metadata_json_safe,
)


class ValidationEngine:
    """
    Pure, deterministic subgoal validation engine (2.3.9).

    Runs all validation rules in a fixed order. No state, no side effects.
    """

    # Fixed rule execution order — must not change between runs.
    _RULES = [
        validate_id_present,
        validate_goal_present,
        validate_parent_consistency,
        validate_state_allowed,
        validate_metadata_json_safe,
    ]

    def validate(self, subgoal: Subgoal) -> List[ValidationError]:
        """
        Run all rules against subgoal and return every ValidationError found.
        Returns an empty list if the subgoal is fully valid.
        """
        errors: List[ValidationError] = []
        for rule in self._RULES:
            result = rule(subgoal)
            if result is not None:
                errors.append(result)
        return errors

    def assert_valid(self, subgoal: Subgoal) -> None:
        """
        Run rules in order and raise on the first ValidationError found.
        No-op if the subgoal is fully valid.
        """
        for rule in self._RULES:
            result = rule(subgoal)
            if result is not None:
                raise result
