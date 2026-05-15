class Policy:
    """
    Behavioural constraints around the core loop.
    MVP: minimal safety + deterministic execution rules.
    """

    MAX_ARGS_SIZE = 2000 # total characters allowed in args
    MAX_TOOL_NAME = 64 # prevent nonsense tool names
    ALLOW_TOOLS = {"echo", "add"} # MVP: explicit allowlist

    def __init__(self, allowed_tools=None, max_args_size=None, max_tool_name=None):
        self.ALLOW_TOOLS = allowed_tools
        self.MAX_ARGS_SIZE = max_args_size
        self.MAX_TOOL_NAME = max_tool_name

    def before_llm(self, user_input: str):
        # No constraints yet — but hook exists for rate limits, etc.
        return

    def after_llm(self, raw_action: dict):
        # Ensure LLM returned a dict
        if not isinstance(raw_action, dict):
            raise ValueError("LLM must return a JSON object")

        # Prevent multi-tool or planning structures
        if "steps" in raw_action or "plan" in raw_action:
            raise ValueError("Planning is not allowed")

        # Prevent nested tool calls
        if any(isinstance(v, dict) and "tool" in v for v in raw_action.values()):
            raise ValueError("Nested tool calls are not allowed")

    def before_execute(self, action: dict):
        tool = action.get("tool")
        args = action.get("args", {})

        # Tool must be allowed
        if tool not in self.ALLOW_TOOLS:
            raise ValueError(f"Tool '{tool}' is not permitted by policy")

        # Tool name sanity
        if not isinstance(tool, str) or len(tool) > self.MAX_TOOL_NAME:
            raise ValueError("Invalid tool name")

        # Args must be a dict
        if not isinstance(args, dict):
            raise ValueError("Args must be a dict")

        # Args size limit
        import json
        size = len(json.dumps(args))
        if size > self.MAX_ARGS_SIZE:
            raise ValueError("Args too large")

    def after_execute(self, result: dict):
        # MVP: no post-execution constraints yet
        return