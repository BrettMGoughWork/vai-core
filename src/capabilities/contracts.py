"""
S2↔S3 boundary contracts (Phase 3.8.1).

Pure dataclasses that define the only shapes allowed to cross the
S2↔S3 boundary for skill invocation and discovery.  They are
deterministic, JSON‑serializable, and contain no runtime logic.

No business logic.  No imports from S1/S2/S3.  No circular
dependencies.  No external libraries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class SkillCallRequest:
    """Request from S2 to S3 to execute a skill."""

    skill_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    context: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.skill_name:
            raise ValueError("skill_name must be non-empty")
        if not isinstance(self.arguments, dict):
            raise ValueError("arguments must be a dict")
        if not self.request_id:
            raise ValueError("request_id must be non-empty")
        if not isinstance(self.context, dict):
            raise ValueError("context must be a dict")


@dataclass(frozen=True)
class SkillResult:
    """Response from S3 to S2 after skill execution."""

    request_id: str
    success: bool
    output: Dict[str, Any] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if (self.output is None) == (self.error is None):
            raise ValueError(
                "Exactly one of output or error must be non-None"
            )
        if not self.request_id:
            raise ValueError("request_id must be non-empty")


@dataclass(frozen=True)
class SkillDiscoveryQuery:
    """Request from S2 to S3 to discover available skills."""

    query: str
    limit: int = 10

    def __post_init__(self) -> None:
        if not self.query:
            raise ValueError("query must be non-empty")
        if self.limit < 1:
            raise ValueError("limit must be >= 1")


@dataclass(frozen=True)
class DiscoveredSkill:
    """Summary of a skill returned by discovery."""

    name: str
    description: str
    score: float = 0.0

    def __post_init__(self) -> None:
        if not (0.0 <= self.score <= 1.0):
            raise ValueError("score must be in [0.0, 1.0]")


@dataclass(frozen=True)
class SkillDiscoveryResult:
    """Response from S3 to S2 with discovered skills."""

    query: SkillDiscoveryQuery
    skills: List[DiscoveredSkill] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Validate descending-score ordering
        for i in range(1, len(self.skills)):
            if self.skills[i - 1].score < self.skills[i].score:
                raise ValueError("skills must be sorted by descending score")
        if len(self.skills) > self.query.limit:
            raise ValueError("len(skills) must not exceed query.limit")
