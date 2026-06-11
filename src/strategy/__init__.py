def __init__(
    self, 
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