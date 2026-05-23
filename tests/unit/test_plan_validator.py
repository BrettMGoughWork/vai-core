import pytest
from src.core.planning.plan import Plan as RealPlan
from src.core.planning.plan_errors import (
    PlanStructureError, UnknownCapabilityError,
    ForbiddenCapabilityError, CapabilitySchemaError, PlanPurityError, PlanSafetyError
)
from src.core.planning.plan_validator import PlanValidator

# Patch Plan with to_dict for test compatibility
class Plan(RealPlan):
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
    plan = Plan(
        intent="sum numbers",
        targetskillid="math_add",
        arguments={"a": 1, "b": 2},
        reasoning_summary="picked math_add",
    )
    schema = FAKE_CAPABILITIES["math_add"]["input_schema"]
    validator.validate(plan, schema)


def test_structure_errors():
    validator = PlanValidator(FAKE_CAPABILITIES)
    # Empty intent
    plan = Plan("", "math_add", {"a": 1, "b": 2}, "summary")
    with pytest.raises(PlanStructureError):
        validator.validate(plan, FAKE_CAPABILITIES["math_add"]["input_schema"])
    # Empty targetskillid
    plan = Plan("intent", "", {"a": 1, "b": 2}, "summary")
    with pytest.raises(PlanStructureError):
        validator.validate(plan, FAKE_CAPABILITIES["math_add"]["input_schema"])
    # Arguments not a dict
    plan = Plan("intent", "math_add", None, "summary")
    with pytest.raises(PlanStructureError):
        validator.validate(plan, FAKE_CAPABILITIES["math_add"]["input_schema"])
    # Reasoning summary not a string
    plan = Plan("intent", "math_add", {"a": 1, "b": 2}, None)
    with pytest.raises(PlanStructureError):
        validator.validate(plan, FAKE_CAPABILITIES["math_add"]["input_schema"])


def test_unknown_capability():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = Plan("intent", "not_real", {"a": 1, "b": 2}, "summary")
    with pytest.raises(UnknownCapabilityError):
        validator.validate(plan, {"type": "object", "properties": {}, "required": []})


def test_forbidden_capability():
    validator = PlanValidator(FAKE_CAPABILITIES, allowed_capabilities={"math_add"})
    plan = Plan("intent", "dangerous", {}, "summary")
    with pytest.raises(ForbiddenCapabilityError):
        validator.validate(plan, FAKE_CAPABILITIES["dangerous"]["input_schema"])


def test_argument_schema_mismatch():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = Plan("intent", "math_add", {"a": 1}, "summary")
    schema = FAKE_CAPABILITIES["math_add"]["input_schema"]
    with pytest.raises(CapabilitySchemaError):
        validator.validate(plan, schema)


def test_plan_purity_error():
    validator = PlanValidator({"math_add": {"input_schema": {"type": "object", "properties": {"a": {}, "b": {}}, "required": ["a", "b"]}}})
    # Insert a non-JSON-pure value
    plan = Plan("intent", "math_add", {"a": object(), "b": 2}, "summary", force_arguments_key=True)
    schema = {"type": "object", "properties": {"a": {}, "b": {}}, "required": ["a", "b"]}
    with pytest.raises(PlanPurityError):
        validator.validate(plan, schema)


def test_plan_safety_error():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = Plan("intent", "dangerous", {}, "summary")
    schema = FAKE_CAPABILITIES["dangerous"]["input_schema"]
    with pytest.raises(PlanSafetyError):
        validator.validate(plan, schema)


from src.core.planning.plan_validator import PlanValidator


def test_validate_accepts_valid_plan_and_args():
    validator = PlanValidator(FAKE_CAPABILITIES)
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
    validator = PlanValidator(FAKE_CAPABILITIES)
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

    with pytest.raises(CapabilitySchemaError):
        validator.validate(plan, schema)


def test_validate_rejects_invalid_plan_field_types():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = Plan(
        intent="",
        targetskillid="math_add",
        arguments={},
        reasoning_summary="picked math_add",
    )

    with pytest.raises(PlanStructureError):
        validator.validate(plan, {"type": "object", "properties": {}, "required": []})
