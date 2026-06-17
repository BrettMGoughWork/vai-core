import pytest
from src.strategy.types.errors import ValidationError
from src.strategy.planning.models.plan import Plan as RealPlan
from src.strategy.types.errors.plan_errors import (
    PlanStructureError,
    ForbiddenCapabilityError, PlanSafetyError
)
from src.strategy.planning.validators.plan_validator import PlanValidator

# Test double: adds to_dict for compatibility without polluting the real Plan class
class PlanTestDouble(RealPlan):
    def __init__(self, *args, force_arguments_key=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._force_arguments_key = force_arguments_key
    def to_dict(self):
        d = {
            "intent": self.intent,
            "targetskillid": self.targetskillid,
            "reasoning_summary": self.reasoning_summary,
        }
        if getattr(self, '_force_arguments_key', False):
            d["arguments"] = self.arguments
        return d

FAKE_CAPABILITIES = {
    "math_add": {"side_effects": None, "input_schema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]}},
    "dangerous": {"side_effects": "file_write", "input_schema": {"type": "object", "properties": {}, "required": []}},
}


def test_valid_plan_passes():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = PlanTestDouble(
        intent="sum numbers",
        targetskillid="math_add",
        arguments={"a": 1, "b": 2},
        reasoning_summary="picked math_add",
    )
    validator.validate(plan)


def test_structure_errors():
    validator = PlanValidator(FAKE_CAPABILITIES)
    # Empty intent
    plan = PlanTestDouble("", "math_add", {"a": 1, "b": 2}, "summary")
    with pytest.raises(PlanStructureError):
        validator.validate(plan)
    # Empty targetskillid
    plan = PlanTestDouble("intent", "", {"a": 1, "b": 2}, "summary")
    with pytest.raises(PlanStructureError):
        validator.validate(plan)
    # Arguments not a dict
    plan = PlanTestDouble("intent", "math_add", None, "summary")
    with pytest.raises(PlanStructureError):
        validator.validate(plan)
    # Reasoning summary not a string
    plan = PlanTestDouble("intent", "math_add", {"a": 1, "b": 2}, None)
    with pytest.raises(PlanStructureError):
        validator.validate(plan)


def test_unknown_capability():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = PlanTestDouble("intent", "not_real", {"a": 1, "b": 2}, "summary")
    with pytest.raises(ValidationError):
        validator.validate(plan)


def test_forbidden_capability():
    validator = PlanValidator(FAKE_CAPABILITIES, allowed_capabilities={"math_add"})
    plan = PlanTestDouble("intent", "dangerous", {}, "summary")
    with pytest.raises(ForbiddenCapabilityError):
        validator.validate(plan)


def test_argument_schema_mismatch():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = PlanTestDouble("intent", "math_add", {"a": 1}, "summary")
    with pytest.raises(ValidationError):
        validator.validate(plan)


def test_plan_purity_error_on_forbidden_output():
    """
    Purity is enforced on capability outputs via enforce_cognitive_purity().
    This test verifies that the pure function rejects forbidden keys.
    (PlanExecutor was removed in R.11.4 — the purity enforcer is tested
    directly here and comprehensively in safety/test_safety.py.)
    """
    from src.strategy.planning.safety.purity_enforcer import enforce_cognitive_purity
    from src.strategy.types.errors.ValidationError import ValidationError

    with pytest.raises(ValidationError, match="Forbidden key 'arguments'"):
        enforce_cognitive_purity({"arguments": "bad"})



def test_plan_safety_error():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = PlanTestDouble("intent", "dangerous", {}, "summary")
    with pytest.raises(PlanSafetyError):
        validator.validate(plan)



def test_validate_accepts_valid_plan_and_args():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = PlanTestDouble(
        intent="sum numbers",
        targetskillid="math_add",
        arguments={"a": 1, "b": 2},
        reasoning_summary="picked math_add",
    )
    
    validator.validate(plan)


def test_validate_rejects_argument_schema_mismatch():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = PlanTestDouble(
        intent="sum numbers",
        targetskillid="math_add",
        arguments={"a": 1},
        reasoning_summary="picked math_add",
    )
    
    with pytest.raises(ValidationError):
        validator.validate(plan)


def test_validate_rejects_invalid_plan_field_types():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = PlanTestDouble(
        intent="",
        targetskillid="math_add",
        arguments={},
        reasoning_summary="picked math_add",
    )

    with pytest.raises(PlanStructureError):
        validator.validate(plan)
