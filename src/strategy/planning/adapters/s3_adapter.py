"""
S2→S3 adapter (Phase 3.8.5).

This is the **only** module in the codebase allowed to import from both
S2-native types and S3 capability contracts.  It performs pure,
deterministic translation between S2's internal representations and
S3's capability contracts, and delegates execution/discovery to the
S3 SkillRunner.

No business logic.  No planning logic.  No execution logic.
No side effects.  No I/O.  No caching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from src.capabilities.contracts import (
    DiscoveredSkill,
    SkillCallRequest,
    SkillDiscoveryQuery,
    SkillDiscoveryResult,
    SkillResult,
)
from src.capabilities.runtime.skill_runner import SkillRunner


# ── S2-native thin wrapper types ────────────────────────────────────────
# These are the only representations S2 code uses.  They have no
# methods, no logic, and must remain pure data containers.


@dataclass(frozen=True)
class S2SkillCallRequest:
    """S2-native skill call request."""
    skill_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class S2SkillResult:
    """S2-native skill result."""
    request_id: str
    success: bool
    output: Optional[dict[str, Any]] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class S2DiscoveryQuery:
    """S2-native discovery query."""
    query: str
    limit: int = 10


@dataclass(frozen=True)
class S2DiscoveredSkill:
    """S2-native discovered skill summary."""
    name: str
    description: str
    score: float = 0.0
    input_schema: dict[str, Any] | None = None
    """Optional input schema describing required parameters (Phase 3.18.3)."""
    output_schema: dict[str, Any] | None = None
    """Optional output schema describing produced keys and types (Phase 3.18.3b)."""


@dataclass(frozen=True)
class S2DiscoveryResult:
    """S2-native discovery result."""
    query: S2DiscoveryQuery
    skills: List[S2DiscoveredSkill] = field(default_factory=list)


# ── S3 Adapter ──────────────────────────────────────────────────────────


class S3Adapter:
    """Pure translation + delegation layer between S2 and S3.

    This is the only class allowed to hold a reference to both S2
    types and the S3 SkillRunner.
    """

    def __init__(self, runner: SkillRunner) -> None:
        self._runner = runner

    # ── discovery ──────────────────────────────────────────────────────

    def discover_skills(self, query: S2DiscoveryQuery) -> S2DiscoveryResult:
        """Convert S2 query → S3, discover, convert result back to S2.

        Args:
            query: An S2-native ``S2DiscoveryQuery``.

        Returns:
            An ``S2DiscoveryResult`` with skills sorted by descending score.
        """
        s3_query = SkillDiscoveryQuery(query=query.query, limit=query.limit)
        s3_result = self._runner.discover(s3_query)
        return self._convert_discovery_result(s3_result)

    # ── execution ──────────────────────────────────────────────────────

    def call_skill(self, request: S2SkillCallRequest) -> S2SkillResult:
        """Convert S2 request → S3, execute, convert result back to S2.

        Args:
            request: An S2-native ``S2SkillCallRequest``.

        Returns:
            An ``S2SkillResult`` with the result of execution.
        """
        s3_request = SkillCallRequest(
            skill_name=request.skill_name,
            arguments=dict(request.arguments),
            request_id=request.request_id,
            context=dict(request.context),
        )
        s3_result = self._runner.execute(s3_request)
        return self._convert_result(s3_result)

    # ── private converters ─────────────────────────────────────────────

    @staticmethod
    def _convert_result(s3: SkillResult) -> S2SkillResult:
        """Convert an S3 ``SkillResult`` to an S2-native ``S2SkillResult``."""
        return S2SkillResult(
            request_id=s3.request_id,
            success=s3.success,
            output=s3.output,
            error=s3.error,
        )

    @staticmethod
    def _convert_discovery_result(
        s3: SkillDiscoveryResult,
    ) -> S2DiscoveryResult:
        """Convert an S3 ``SkillDiscoveryResult`` to an S2-native form."""
        s2_skills = [
            S2DiscoveredSkill(
                name=sk.name,
                description=sk.description,
                score=sk.score,
                input_schema=sk.input_schema,
                output_schema=sk.output_schema,
            )
            for sk in s3.skills
        ]
        s2_query = S2DiscoveryQuery(
            query=s3.query.query,
            limit=s3.query.limit,
        )
        return S2DiscoveryResult(query=s2_query, skills=s2_skills)
