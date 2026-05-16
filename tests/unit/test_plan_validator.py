import pytest

from src.core.planning.plan import Plan
from src.core.planning.plan_validator import PlanValidationError, PlanValidator


def test_validate_accepts_valid_plan_and_args():
    validator = PlanValidator()
    plan = Plan(
        intent="sum numbers",
        targetskillid="math_add",
        arguments={"a": 1, "b": 2},
        reasoning_summary="picked math_add",
    )
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    }

    validator.validate(plan, schema)


def test_validate_rejects_argument_schema_mismatch():
    validator = PlanValidator()
    plan = Plan(
        intent="sum numbers",
        targetskillid="math_add",
        arguments={"a": 1},
        reasoning_summary="picked math_add",
    )
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    }

    with pytest.raises(PlanValidationError, match="Plan arguments do not match skill input schema"):
        validator.validate(plan, schema)


def test_validate_rejects_invalid_plan_field_types():
    validator = PlanValidator()
    plan = Plan(
        intent="",
        targetskillid="math_add",
        arguments={},
        reasoning_summary="picked math_add",
    )

    with pytest.raises(PlanValidationError, match="intent must be a non-empty string"):
        validator.validate(plan, {"type": "object", "properties": {}, "required": []})
