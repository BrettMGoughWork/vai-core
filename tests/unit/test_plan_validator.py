import pytest
from src.capabilities.validator import ValidationError
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
    validator.validate(plan)


def test_structure_errors():
    validator = PlanValidator(FAKE_CAPABILITIES)
    # Empty intent
    plan = Plan("", "math_add", {"a": 1, "b": 2}, "summary")
    with pytest.raises(PlanStructureError):
        validator.validate(plan)
    # Empty targetskillid
    plan = Plan("intent", "", {"a": 1, "b": 2}, "summary")
    with pytest.raises(PlanStructureError):
        validator.validate(plan)
    # Arguments not a dict
    plan = Plan("intent", "math_add", None, "summary")
    with pytest.raises(PlanStructureError):
        validator.validate(plan)
    # Reasoning summary not a string
    plan = Plan("intent", "math_add", {"a": 1, "b": 2}, None)
    with pytest.raises(PlanStructureError):
        validator.validate(plan)


def test_unknown_capability():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = Plan("intent", "not_real", {"a": 1, "b": 2}, "summary")
    with pytest.raises(ValidationError):
        validator.validate(plan)


def test_forbidden_capability():
    validator = PlanValidator(FAKE_CAPABILITIES, allowed_capabilities={"math_add"})
    plan = Plan("intent", "dangerous", {}, "summary")
    with pytest.raises(ForbiddenCapabilityError):
        validator.validate(plan)


def test_argument_schema_mismatch():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = Plan("intent", "math_add", {"a": 1}, "summary")
    with pytest.raises(ValidationError):
        validator.validate(plan)


def test_plan_purity_error_on_capability_output():
    """
    Purity is enforced on capability outputs, not on PlanValidator.
    This test creates a dummy capability that returns a forbidden key in its output.
    """
    from src.core.planning.plan_executor import PlanExecutor
    from src.core.types.errors.ValidationError import ValidationError
    from src.core.planning.plan_state import PlanState
    from src.core.types.step_state import StepState
    from src.core.types.step_result import StepResult, StepOutcome

    class DummyCapability:
        def execute(self, arguments):
            return {"arguments": "bad"}  # forbidden key

    class DummyDispatcher:
        def __init__(self):
            self.core_step = type("CoreStep", (), {"capabilities": {"dummy": {}}})()
        def dispatch(self, plan, plan_state=None):
            # Always return a successful StepState and forbidden output
            from src.core.types.step_state import StepStatus
            return StepState(
                step_id="dummy",
                parent_id=None,
                cognitive_input={},
                last_result=None,
                status=StepStatus.PENDING,
                created_at=0,
                attempt=0,
                trace=[],
                canonical_hash="testhash"
            ), StepResult(
                outcome=StepOutcome.SUCCESS,
                reason="",
                payload=DummyCapability().execute(plan.arguments),
                trace={},
            )

    plan = Plan("intent", "dummy", {}, "summary")
    executor = PlanExecutor(DummyDispatcher())
    with pytest.raises(ValidationError):
        executor.execute(plan)



def test_plan_safety_error():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = Plan("intent", "dangerous", {}, "summary")
    with pytest.raises(PlanSafetyError):
        validator.validate(plan)


from src.core.planning.plan_validator import PlanValidator


def test_validate_accepts_valid_plan_and_args():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = Plan(
        intent="sum numbers",
        targetskillid="math_add",
        arguments={"a": 1, "b": 2},
        reasoning_summary="picked math_add",
    )
    
    validator.validate(plan)


def test_validate_rejects_argument_schema_mismatch():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = Plan(
        intent="sum numbers",
        targetskillid="math_add",
        arguments={"a": 1},
        reasoning_summary="picked math_add",
    )
    
    with pytest.raises(ValidationError):
        validator.validate(plan)


def test_validate_rejects_invalid_plan_field_types():
    validator = PlanValidator(FAKE_CAPABILITIES)
    plan = Plan(
        intent="",
        targetskillid="math_add",
        arguments={},
        reasoning_summary="picked math_add",
    )

    with pytest.raises(PlanStructureError):
        validator.validate(plan)
