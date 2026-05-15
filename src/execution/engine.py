from __future__ import annotations
from typing import Any, Dict

from src.core.skills.base import BaseSkill
from src.execution.errors import ToolExecutionError


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
        return skill.run(**args)

    except Exception as e:
        raise ToolExecutionError(f"Tool '{skill.name}' failed: {e}") from e