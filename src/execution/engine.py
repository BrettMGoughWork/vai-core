from __future__ import annotations
from typing import Any, Dict

from src.primitives.base import BaseSkill
from src.execution.errors import ToolExecutionError
from src.core.types.result import CoreResult

def execute_tool(skill: BaseSkill, args: Dict[str, Any]) -> Any:
    """
    Execute a skill with full validation + canonicalisation pipeline.
    This is the single entrypoint for tool execution.
    """

    try:
        # BaseSkill.run() already performs:
        # - canonicalisation
        # - structural validation
        # - semantic validation
        # - handler execution
        output = skill.run(**args)
        return CoreResult.from_tool(skill.name, output)

    except Exception as e:
        return CoreResult.from_error(
            ToolExecutionError(f"Tool '{skill.name}' failed: {e}")
        )
