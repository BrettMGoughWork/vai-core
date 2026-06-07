from typing import List
from src.core.types.toolspec import ToolSpec
from src.core.types.capabilities import SkillCategory
from src.core.types.capabilities import SideEffect
from .errors import GovernanceError


def select_tool(
    tool_name: str,
    allowed_tools: List[str],
    allowed_categories: List[SkillCategory],
    allowed_side_effects: List[SideEffect],
    registry,
) -> ToolSpec:

    # 1. Tool must exist
    spec = registry.get_spec(tool_name)
    if spec is None:
        raise GovernanceError(f"Tool '{tool_name}' does not exist")

    # 2. Tool must be explicitly allowed
    if tool_name not in allowed_tools:
        raise GovernanceError(f"Tool '{tool_name}' is not allowed")

    # 3. Category must be allowed
    if spec.category not in allowed_categories:
        raise GovernanceError(
            f"Tool '{tool_name}' category '{spec.category}' not permitted"
        )

    # 4. Side-effects must be allowed
    if spec.side_effects not in allowed_side_effects:
        raise GovernanceError(
            f"Tool '{tool_name}' side-effects '{spec.side_effects}' not permitted"
        )

    # 5. Tool must be enabled
    if not spec.enabled:
        raise GovernanceError(f"Tool '{tool_name}' is disabled")

    return spec