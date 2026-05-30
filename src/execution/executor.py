from typing import Any, Dict

from pydantic.dataclasses import dataclass

@dataclass
class ExecutionResult:
    status: str
    output: Any | None
    error: Any | None
    skill_id: str
    raw_response: Any | None

class Executor:
    """
    Executes canonical actions by routing them to skills.
    MVP: sync, single-tool, no parallelism.
    """

    def __init__(self, registry):
        self.registry = registry

    def execute(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """
        action = { "tool": "echo", "args": { "text": "hi" } }
        """
        tool_name = action.get("tool")
        args = action.get("args", {})

        if not isinstance(args, dict):
            raise ValueError("Executor expected 'args' to be a dict")

        func = self.registry.get(tool_name)
        if func is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        result = func(**args)

        return {
            "tool": tool_name,
            "args": args,
            "result": result,
        }