from __future__ import annotations

from typing import Any

from src.core.skills.registry import SkillRegistry
from src.execution.executor_contract import Executor

try:
    from src.skills.skill_filter import SkillFilter
except ModuleNotFoundError:
    from src.core.skills.skillfilter import SkillFilter

try:
    from src.skills.skill_ranker import SkillRanker
except ModuleNotFoundError:
    SkillRanker = Any  # type: ignore[assignment]

try:
    from src.core.planning.local_planner import LocalPlanner
except ModuleNotFoundError:
    LocalPlanner = Any  # type: ignore[assignment]

try:
    from src.core.planning.plan_validator import PlanValidator
except ModuleNotFoundError:
    from src.core.planning.planvalidator import PlanValidator


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


class CoreLoop:
    """
    One LLM call → one action → canonicalise → execute.
    No recursion, no planning, no multi-step loops.
    """

    def __init__(self, 
        llm, 
        governance, 
        executor, 
        policy=None, 
        cache=None, 
        logger=None, 
        telemetry=None):
        
        self.llm = llm
        self.governance = governance
        self.executor = executor
        self.policy = policy
        self.cache = cache
        self.logger = logger
        self.telemetry = telemetry

    def run(self, user_input: str) -> dict:
        # 1. Policy: before LLM
        if self.policy:
            self.policy.before_llm(user_input)

        # 2. LLM → raw action
        if self.logger:
            self.logger.core("llm_input", {"input": user_input})
        if self.telemetry:
            self.telemetry.inc("llm_calls")            
            with self.telemetry.time("llm_latency"):
                raw_action = self.llm.complete(user_input)
        else:
            raw_action = self.llm.complete(user_input)
    
        if self.logger:
            self.logger.core("llm_output", {"output": raw_action})

        # 3. Policy: after LLM
        if self.policy:
            self.policy.after_llm(raw_action)

        # 4. Cache lookup
        action = None
        if self.cache:
            fp = self.cache.fingerprint(raw_action)
            cached = self.cache.get(fp)
            if cached and self.telemetry:
                self.telemetry.inc("cache_hits")
            if self.logger:
                self.logger.core("cache_lookup", {"fingerprint": fp, "cached": cached is not None})
            if cached:
                action = cached
            else:
                action = self.cache.get(fp)
                self.cache.set(fp, action)

        # 5. Canonicalise if not cached
        if action is None:
            action = self.governance.canonicalise(raw_action)
            if self.cache:
                self.cache.set(fp, action)
            if self.logger:
                self.logger.core("canonical_action", {"action": action})

        if self.logger:
            self.logger.core("final_action", {"action": action})

        # 6. Policy: before execute
        if self.policy:
            self.policy.before_execute(action)

        # 7. Execute
        if self.logger:
            self.logger.execution("execute_action", {"action": action})
        result = self.executor.execute(action)

        # 8. Policy: after execute
        if self.policy:
            self.policy.after_execute(result)
        if self.logger:
            self.logger.execution("execute_result", {"result": result})
        if self.telemetry:
            self.telemetry.inc("executions")

        return result