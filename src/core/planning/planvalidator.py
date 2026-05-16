import json
import os
from jsonschema import validate, ValidationError

from src.core.planning.plan import Plan


class PlanValidationError(Exception):
    """Raised when a Plan fails validation."""
    pass


class PlanValidator:
    def __init__(self):
        schema_path = os.path.join(os.path.dirname(__file__), "plan.schema.json")
        with open(schema_path, "r") as f:
            self._plan_schema = json.load(f)

    def validate(self, plan: Plan, skillinputschema: dict) -> None:
        """
        Validate a Plan against the plan schema and skill input schema.
        
        Args:
            plan: The Plan object to validate.
            skillinputschema: The JSON schema for the skill's input arguments.
        
        Raises:
            PlanValidationError: If validation fails.
        """
        plan_dict = {
            "intent": plan.intent,
            "targetskillid": plan.targetskillid,
            "arguments": plan.arguments,
            "reasoning_summary": plan.reasoning_summary,
        }
        
        try:
            validate(instance=plan_dict, schema=self._plan_schema)
        except ValidationError as e:
            raise PlanValidationError(f"Plan does not match plan schema: {e.message}") from e
        
        try:
            validate(instance=plan.arguments, schema=skillinputschema)
        except ValidationError as e:
            raise PlanValidationError(f"Plan arguments do not match skill input schema: {e.message}") from e
