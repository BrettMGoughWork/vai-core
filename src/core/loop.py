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