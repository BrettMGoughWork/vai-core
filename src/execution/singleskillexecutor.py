from __future__ import annotations

from typing import Any

from src.core.planning.plan import Plan
from src.capabilities.registry import SkillRegistry
from src.capabilities.skill import Skill
from src.capabilities import validator
from src.execution.executor_contract import ExecutionResult, Executor


class SingleSkillExecutor(Executor):
    def execute(self, plan: Plan) -> ExecutionResult:
        raw_response: Any | None = None

        try:
            skill: Skill | Any = SkillRegistry.get(plan.targetskillid)

            input_schema = getattr(skill, "input_schema", None)
            if input_schema is None:
                input_schema = getattr(skill, "schema", None)
            if not isinstance(input_schema, dict):
                raise validator.ValidationError(
                    f"Skill '{plan.targetskillid}' does not expose an input schema"
                )

            validator.validate_structural(input_schema, plan.arguments)

            if hasattr(skill, "execute"):
                raw_response = skill.execute(plan.arguments)
            elif hasattr(skill, "run"):
                raw_response = skill.run(**plan.arguments)
            else:
                raise TypeError(
                    f"Skill '{plan.targetskillid}' is not executable (missing execute)"
                )

            output_schema = getattr(skill, "output_schema", None)
            if output_schema is None:
                output_schema = getattr(getattr(skill, "metadata", None), "output_schema", None)
            if not isinstance(output_schema, dict):
                raise validator.ValidationError(
                    f"Skill '{plan.targetskillid}' does not expose an output schema"
                )
            if not isinstance(raw_response, dict):
                raise validator.ValidationError(
                    f"Skill '{plan.targetskillid}' output must be an object for schema validation"
                )

            validator.validate_structural(output_schema, raw_response)

            return ExecutionResult(
                status="success",
                output=raw_response,
                error=None,
                skill_id=plan.targetskillid,
                raw_response=raw_response,
            )
        except Exception as error:
            return ExecutionResult(
                status="error",
                output=None,
                error=error,
                skill_id=plan.targetskillid,
                raw_response=raw_response,
            )
