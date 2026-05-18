from __future__ import annotations

from typing import Any

from src.skills.registry import SkillRegistry
from src.execution.executor_contract import Executor
from src.skills.skill_filter import SkillFilter
from src.skills.skill_ranker import SkillRanker
from src.core.planning.local_planner import LocalPlanner
from src.core.planning.plan_validator import PlanValidator


class CoreStep:
    def __init__(
        self,
        skill_filter: SkillFilter,
        skill_ranker: SkillRanker,
        planner: LocalPlanner,
        plan_validator: PlanValidator,
        executor: Executor,
    ):
        self.skill_filter = skill_filter
        self.skill_ranker = skill_ranker
        self.planner = planner
        self.plan_validator = plan_validator
        self.executor = executor

    def _log(self, event: str, payload: Any) -> None:
        pass

    def run(self, user_message: str, state: dict) -> dict:
        try:
            available_skills = state.get("skills", [])
            filtered = self.skill_filter.filter(available_skills, user_message)
            self._log("filtered", filtered)

            ranked = self.skill_ranker.rank(filtered, user_message)
            self._log("ranked", ranked)

            plan = self.planner.plan(user_message, ranked)
            self._log("plan", plan)

            skill_spec = SkillRegistry.get(plan.targetskillid)
            skillinput_schema = skill_spec.schema
            self.plan_validator.validate(plan, skillinput_schema)
            self._log("validated_plan", plan)

            result = self.executor.execute(plan)
            self._log("execution_result", result)

            state["lastusermessage"] = user_message
            state["last_plan"] = plan
            state["lastexecutionresult"] = result
            return state
        except Exception as error:
            state["last_error"] = error
            return state