from dataclasses import dataclass
from typing import Any, Callable, Dict

from .categories import SkillCategory
from .side_effects import SideEffect
    
@dataclass
class ToolSpec:
    """
    Canonical description of a tool/skill exposed to the LLM.
    """

    # Unique name exposed to the LLM
    name: str

    # Human-readable description (LLM sees this)
    description: str

    # JSON schema describing the tool's input arguments
    schema: Dict[str, Any]

    # Python callable that actually executes the tool
    handler: Callable[..., Any]

    # Optional: category for governance (fs, http, math, text, dangerous, etc.)
    category: SkillCategory = SkillCategory.GENERAL

    # Optional: whether this tool has side effects (write, network, etc.)
    side_effects: SideEffect = SideEffect.NONE

    # Optional: whether this tool is allowed by default
    enabled: bool = True

    # Optional: whether to hide this tool from the LLM (for internal use only)
    hidden: bool = False

    # Optional: whether this tool is only for development/testing and should not be used in production
    dev_only: bool = False

    # Optional: whether retries may assume the tool is idempotent
    is_idempotent: bool = True

    def run(self, **kwargs) -> Any:
        """
        Execute the tool with validated arguments.
        Validation is handled by BaseSkill before calling this.
        """
        return self.handler(**kwargs)

    def execute(self, args: dict[str, Any]) -> Any:
        return self.run(**args)