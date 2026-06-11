"""
Behaviour tests for 2.3.9 Subgoal Validation Rules and ValidationEngine.

Design principles:
- Fakes over mocks: build Subgoal instances directly; bypass __post_init__
  guards only where necessary to test invalid-state rules.
- Behaviour focus: test what is validated, not how rules are stored.
- One test per rule violation + combined and ordering tests.
"""
from __future__ import annotations

import pytest

from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState
from src.strategy.types.errors.ValidationError import ValidationError
from src.strategy.planning.subgoals.validation_engine import ValidationEngine
from src.strategy.planning.subgoals.validation_rules import (
    validate_id_present,
    validate_goal_present,
    validate_parent_consistency,
    validate_state_allowed,
    validate_metadata_json_safe,
)


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------

def valid_subgoal(**overrides) -> Subgoal:
    """Build a minimal, fully valid Subgoal."""
    defaults = dict(
        subgoal_id="sg-001",
        goal="accomplish something",
        context={},
        metadata={"tag": "test"},
        parent_id=None,
        state=SubgoalLifecycleState.CREATED,
    )
    defaults.update(overrides)
    return Subgoal(**defaults)


def subgoal_with_bad_state(base: Subgoal, bad_state) -> Subgoal:
    """Return a copy of base with state replaced by an arbitrary value,
    bypassing the enum enforcement."""
    obj = object.__new__(Subgoal)
    for f in base.__dataclass_fields__:
        if f == "canonical_hash":
            continue
        object.__setattr__(obj, f, getattr(base, f))
    object.__setattr__(obj, "state", bad_state)
    object.__setattr__(obj, "canonical_hash", "fake-hash")
    return obj


@pytest.fixture
def engine() -> ValidationEngine:
    return ValidationEngine()


# ---------------------------------------------------------------------------
# Individual rule tests
# ---------------------------------------------------------------------------

class TestValidateIdPresent:
    def test_valid_id_passes(self):
        assert validate_id_present(valid_subgoal()) is None

    def test_empty_string_fails(self):
        sg = valid_subgoal(subgoal_id="")
        result = validate_id_present(sg)
        assert isinstance(result, ValidationError)
        assert result.details["rule"] == "validate_id_present"

    def test_whitespace_only_fails(self):
        sg = valid_subgoal(subgoal_id="   ")
        assert validate_id_present(sg) is not None


class TestValidateGoalPresent:
    def test_valid_goal_passes(self):
        assert validate_goal_present(valid_subgoal()) is None

    def test_empty_goal_fails(self):
        sg = valid_subgoal(goal="")
        result = validate_goal_present(sg)
        assert isinstance(result, ValidationError)
        assert result.details["rule"] == "validate_goal_present"
        assert result.details["field"] == "goal"

    def test_whitespace_only_goal_fails(self):
        sg = valid_subgoal(goal="   ")
        assert validate_goal_present(sg) is not None


class TestValidateParentConsistency:
    def test_no_parent_passes(self):
        sg = valid_subgoal(parent_id=None)
        assert validate_parent_consistency(sg) is None

    def test_different_parent_passes(self):
        sg = valid_subgoal(subgoal_id="sg-001", parent_id="sg-000")
        assert validate_parent_consistency(sg) is None

    def test_self_referential_parent_fails(self):
        sg = valid_subgoal(subgoal_id="sg-001", parent_id="sg-001")
        result = validate_parent_consistency(sg)
        assert isinstance(result, ValidationError)
        assert result.details["rule"] == "validate_parent_consistency"
        assert result.details["field"] == "parent_id"


class TestValidateStateAllowed:
    def test_valid_state_passes(self):
        for state in SubgoalLifecycleState:
            sg = valid_subgoal(state=state)
            assert validate_state_allowed(sg) is None

    def test_invalid_state_fails(self):
        sg = subgoal_with_bad_state(valid_subgoal(), "not_a_real_state")
        result = validate_state_allowed(sg)
        assert isinstance(result, ValidationError)
        assert result.details["rule"] == "validate_state_allowed"


class TestValidateMetadataJsonSafe:
    def test_valid_metadata_passes(self):
        sg = valid_subgoal(metadata={"key": "value", "count": 3})
        assert validate_metadata_json_safe(sg) is None

    def test_empty_metadata_passes(self):
        sg = valid_subgoal(metadata={})
        assert validate_metadata_json_safe(sg) is None

    def test_nested_metadata_passes(self):
        sg = valid_subgoal(metadata={"nested": {"a": [1, 2, 3]}})
        assert validate_metadata_json_safe(sg) is None


# ---------------------------------------------------------------------------
# ValidationEngine — combined behaviour
# ---------------------------------------------------------------------------

class TestValidationEngine:
    def test_valid_subgoal_returns_empty_list(self, engine):
        errors = engine.validate(valid_subgoal())
        assert errors == []

    def test_single_violation_returns_one_error(self, engine):
        sg = valid_subgoal(goal="")
        errors = engine.validate(sg)
        assert len(errors) == 1
        assert errors[0].details["rule"] == "validate_goal_present"

    def test_multiple_violations_all_returned(self, engine):
        sg = valid_subgoal(subgoal_id="", goal="")
        errors = engine.validate(sg)
        rules_hit = {e.details["rule"] for e in errors}
        assert "validate_id_present" in rules_hit
        assert "validate_goal_present" in rules_hit

    def test_all_errors_are_validation_error_instances(self, engine):
        sg = valid_subgoal(subgoal_id="", goal="")
        for error in engine.validate(sg):
            assert isinstance(error, ValidationError)

    def test_deterministic_ordering(self, engine):
        """Same input always produces same error ordering."""
        sg = valid_subgoal(subgoal_id="", goal="")
        r1 = engine.validate(sg)
        r2 = engine.validate(sg)
        assert [e.details["rule"] for e in r1] == [e.details["rule"] for e in r2]

    def test_rules_run_in_fixed_order(self, engine):
        """id rule fires before goal rule — mirrors _RULES list order."""
        sg = valid_subgoal(subgoal_id="", goal="")
        errors = engine.validate(sg)
        rules = [e.details["rule"] for e in errors]
        assert rules.index("validate_id_present") < rules.index("validate_goal_present")

    def test_self_referential_parent_detected(self, engine):
        sg = valid_subgoal(subgoal_id="sg-x", parent_id="sg-x")
        errors = engine.validate(sg)
        assert any(e.details["rule"] == "validate_parent_consistency" for e in errors)


class TestAssertValid:
    def test_valid_subgoal_does_not_raise(self, engine):
        engine.assert_valid(valid_subgoal())  # must not raise

    def test_raises_on_first_error(self, engine):
        sg = valid_subgoal(subgoal_id="", goal="")
        with pytest.raises(ValidationError) as exc_info:
            engine.assert_valid(sg)
        # First rule in order is validate_id_present
        assert exc_info.value.details["rule"] == "validate_id_present"

    def test_raises_validation_error_type(self, engine):
        sg = valid_subgoal(goal="")
        with pytest.raises(ValidationError):
            engine.assert_valid(sg)

    def test_stops_at_first_error(self, engine):
        """assert_valid raises immediately — subsequent rules are not checked."""
        sg = valid_subgoal(subgoal_id="", goal="")
        with pytest.raises(ValidationError) as exc_info:
            engine.assert_valid(sg)
        # Only the first rule's error is raised, not a combined list
        assert exc_info.value.details["rule"] == "validate_id_present"