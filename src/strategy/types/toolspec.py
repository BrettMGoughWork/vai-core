"""
Domain-level ToolSpec contract shared across all strata.

ToolSpec is the canonical description of a tool exposed to the LLM.
It lives in the domain layer (S2) so infrastructure can depend on it
without importing from the capability layer (S3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from src.strategy.types.capabilities import SkillCategory, SideEffect


@dataclass
class ToolSpec:
    """Canonical description of a tool/skill exposed to the LLM."""

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

    # Optional: whether this tool is only for development/testing
    dev_only: bool = False

    # Optional: whether retries may assume the tool is idempotent
    is_idempotent: bool = True

    # --- capability execution model metadata ---
    # Is this capability expected to be deterministic (same input -> same output)?
    deterministic: bool = True

    # Is this capability pure from S2's perspective?
    pure: bool = True

    # Expected output shape for validation and test generation
    output_schema: Optional[Dict[str, Any]] = field(default=None)

    def run(self, **kwargs) -> Any:
        """Execute the tool with validated arguments."""
        return self.handler(**kwargs)
