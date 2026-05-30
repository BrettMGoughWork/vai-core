"""
Subgoal validation rules for phase 2.3.9.

Each rule is a pure function:
    (Subgoal) -> ValidationError | None

None means the subgoal passes that rule.
Rules must not mutate the subgoal or any external state.

Skipped rules (no backing fields on Subgoal):
  - validate_steps_nonempty
  - validate_steps_unique
  - validate_dependencies_acyclic
"""
from __future__ import annotations

import json
from typing import Optional

from src.core.types.subgoal import Subgoal, SubgoalLifecycleState
from src.core.planning.subgoals.validation_errors import ValidationError


def validate_id_present(subgoal: Subgoal) -> Optional[ValidationError]:
    if not subgoal.subgoal_id or not subgoal.subgoal_id.strip():
        return ValidationError(
            message="Subgoal ID must be non-empty",
            details={"rule": "validate_id_present", "field": "subgoal_id"},
        )
    return None


def validate_goal_present(subgoal: Subgoal) -> Optional[ValidationError]:
    if not subgoal.goal or not subgoal.goal.strip():
        return ValidationError(
            message="Subgoal goal must be non-empty",
            details={"rule": "validate_goal_present", "field": "goal"},
        )
    return None


def validate_parent_consistency(subgoal: Subgoal) -> Optional[ValidationError]:
    if subgoal.parent_id is not None and subgoal.parent_id == subgoal.subgoal_id:
        return ValidationError(
            message="Subgoal parent_id must not equal its own subgoal_id",
            details={"rule": "validate_parent_consistency", "field": "parent_id"},
        )
    return None


def validate_state_allowed(subgoal: Subgoal) -> Optional[ValidationError]:
    if not isinstance(subgoal.state, SubgoalLifecycleState):
        return ValidationError(
            message=f"Subgoal state {subgoal.state!r} is not a valid SubgoalLifecycleState",
            details={"rule": "validate_state_allowed", "field": "state"},
        )
    return None


def validate_metadata_json_safe(subgoal: Subgoal) -> Optional[ValidationError]:
    try:
        json.dumps(subgoal.metadata)
    except (TypeError, ValueError) as exc:
        return ValidationError(
            message=f"Subgoal metadata is not JSON-serializable: {exc}",
            details={"rule": "validate_metadata_json_safe", "field": "metadata"},
        )
    return None
