# deadcode_ignore — I6 false positive: helper class, not a test
class ToolValidator:
    """
    MVP: validate canonical actions against the generated tool schema.
    """

    def __init__(self, schema: dict):
        self.schema = schema

    def validate(self, action: dict):
        tool = action.get("tool")
        args = action.get("args", {})

        if tool not in self.schema:
            raise ValueError(f"Unknown tool '{tool}'")

        spec = self.schema[tool]
        expected_args = spec["args"]

        # 1. Check for missing required args
        for arg_name in expected_args:
            if arg_name not in args:
                raise ValueError(f"Missing required arg '{arg_name}' for tool '{tool}'")

        # 2. Check for unknown args
        for arg_name in args:
            if arg_name not in expected_args:
                raise ValueError(f"Unknown arg '{arg_name}' for tool '{tool}'")

        # 3. Type checking
        for arg_name, meta in expected_args.items():
            expected_type = meta["type"]
            value = args[arg_name]

            if expected_type == "string" and not isinstance(value, str):
                raise ValueError(f"Arg '{arg_name}' must be a string")

            if expected_type == "number" and not isinstance(value, (int, float)):
                raise ValueError(f"Arg '{arg_name}' must be a number")

            # MVP: everything else is allowed