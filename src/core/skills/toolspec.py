from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


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
    category: str = "general"

    # Optional: whether this tool has side effects (write, network, etc.)
    side_effects: bool = False

    # Optional: whether this tool is allowed by default
    enabled: bool = True

    def run(self, **kwargs) -> Any:
        """
        Execute the tool with validated arguments.
        Validation is handled by BaseSkill before calling this.
        """
        return self.handler(**kwargs)