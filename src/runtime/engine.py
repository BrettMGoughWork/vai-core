from __future__ import annotations

from typing import Any, Dict

from src.runtime.errors import ToolExecutionError
from src.runtime.types.result import CoreResult


def execute_tool(skill: Any, args: Dict[str, Any]) -> CoreResult:
    """Execute a skill and return a CoreResult.

    This is a thin S1 wrapper. Validation, drift detection and schema
    enforcement are handled by the S5 ValidationPipeline.
    """
    try:
        output = skill.run(**args)
        return CoreResult.from_tool(skill.name, output)
    except Exception as e:
        return CoreResult.from_error(
            ToolExecutionError(f"Tool '{skill.name}' failed: {e}")
        )
