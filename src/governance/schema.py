class Governance:
    """
    Governance enforces the shape of actions.
    MVP: minimal canonicalisation + minimal validation.
    """

    REQUIRED_KEYS = ["tool", "args"]

    def __init__(self, validator=None):
        self.validator = validator

    def canonicalise(self, raw_action: dict) -> dict:
        # 1. Ensure dict
        if not isinstance(raw_action, dict):
            raise ValueError("LLM output must be a dict")

        # 2. Extract tool
        tool = raw_action.get("tool") or raw_action.get("action")
        if isinstance(tool, list) and len(tool) == 1:
            tool = tool[0]
        if not isinstance(tool, str):
            raise ValueError("Action 'tool' must be a string")

        # 3. Extract args
        args = raw_action.get("args")
        if args is None:
            # infer args from other fields
            args = {k: v for k, v in raw_action.items() if k not in ["tool", "action"]}
        if not isinstance(args, dict):
            args = {"value": args}

        # 4. Build canonical action
        action = {"tool": tool, "args": args}

        # 5. Validate
        self.validate(action)

        if self.validator:
            self.validator.validate(action)
        
        return action

    def validate(self, action: dict) -> None:
        if not isinstance(action, dict):
            raise ValueError("Action must be a dict")

        for key in self.REQUIRED_KEYS:
            if key not in action:
                raise ValueError(f"Missing required key: {key}")

        if not isinstance(action["tool"], str):
            raise ValueError("Action 'tool' must be a string")