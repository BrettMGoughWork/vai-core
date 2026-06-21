"""
Pattern type definitions for S3 instructional capabilities.

A pattern is an instructional (LLM-readable) capability that teaches
an agent how to compose primitives to achieve a goal. Unlike workflows
(deterministic step graphs) or primitives (atomic execution), patterns
are natural-language instructions interpreted by the LLM at runtime.

Canonical home for cross-stratum pattern type sharing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered pattern, injected as LLM context on demand")
@dataclass(frozen=True)
class PatternDefinition:
    """Declarative definition of a pattern capability.

    Fields
    ------
    pattern_id:
        Stable, unique identifier (e.g. ``reply_to_email``, ``triage_inbox``).
    name:
        Human-readable name for display and discovery.
    description:
        Short summary of what the pattern accomplishes.
    primitives:
        List of primitive tool names required by this pattern.
        An agent referencing this pattern does not need to list these
        primitives explicitly — the pattern acts as a capability gateway.
    instructions:
        Natural-language instructions injected into the LLM context.
        Describes step-by-step how to use the listed primitives to
        accomplish the goal.
    version:
        Semver version string for evolvability.
    """

    pattern_id: str
    name: str
    description: str = ""
    primitives: List[str] = field(default_factory=list)
    instructions: str = ""
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not self.pattern_id:
            raise ValueError("pattern_id must be non-empty")
        if not self.name:
            raise ValueError("name must be non-empty")
        if not self.instructions:
            raise ValueError("instructions must be non-empty")
        if not isinstance(self.primitives, list):
            raise ValueError("primitives must be a list")
