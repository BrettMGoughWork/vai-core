from __future__ import annotations

from src.core.planning.plan import Plan
from src.skills.validator import ValidationError, validate_structural


class PlanValidationError(Exception):
    pass


class PlanValidator:
    def validate(self, plan: Plan, skillinput_schema: dict) -> None:
        if not isinstance(plan.intent, str) or not plan.intent:
            raise PlanValidationError("Plan intent must be a non-empty string")
        if not isinstance(plan.targetskillid, str) or not plan.targetskillid:
            raise PlanValidationError("Plan targetskillid must be a non-empty string")
        if not isinstance(plan.arguments, dict):
            raise PlanValidationError("Plan arguments must be an object")
        if not isinstance(plan.reasoning_summary, str):
            raise PlanValidationError("Plan reasoning_summary must be a string")
        if not isinstance(skillinput_schema, dict):
            raise PlanValidationError("Skill input schema must be an object")

        try:
            validate_structural(skillinput_schema, plan.arguments)
        except ValidationError as exc:
            raise PlanValidationError(
                f"Plan arguments do not match skill input schema: {exc}"
            ) from exc
