"""
S2→S3 runtime entry point (Phase 3.0.1).

The SkillRunner is the single entry point for Stratum 2 to call into
Stratum 3. It receives SkillCallRequests, resolves the appropriate
skill, executes it, and returns SkillResults. It also supports skill
discovery via ``discover()``, wrapping the registry's semantic search.
"""

from __future__ import annotations

from typing import Callable, Optional

from src.capabilities.contracts import (
    DiscoveredSkill,
    SkillCallRequest,
    SkillDiscoveryQuery,
    SkillDiscoveryResult,
    SkillResult,
)
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.skills.executor import SkillExecutor


class SkillRunner:
    """
    Entry point for S2→S3 skill calls and discovery.

    Usage from S2:
        runner = SkillRunner()
        result = runner.execute(SkillCallRequest(
            skill_name="file.read",
            arguments={"path": "/tmp/test.txt"},
        ))
    """

    def __init__(
        self,
        registry: Optional[CapabilitySkillRegistry] = None,
        embedding_fn: Optional[Callable[[str], list[float]]] = None,
    ):
        self._registry: CapabilitySkillRegistry = CapabilitySkillRegistry() if registry is None else registry
        self._executor = SkillExecutor()
        self._embedding_fn = embedding_fn

    def execute(self, request: SkillCallRequest) -> SkillResult:
        """
        Execute a skill call from S2.

        Resolves the skill name to a primitive via the registry,
        validates inputs, and executes the handler.

        Args:
            request: SkillCallRequest with skill_name, arguments, and request_id.

        Returns:
            SkillResult with success/failure status and output.
        """
        try:
            spec = self._registry.get(request.skill_name)
            output = spec.run(**request.arguments)
            return SkillResult(
                request_id=request.request_id,
                success=True,
                output=output,
            )

        except Exception as exc:
            return SkillResult(
                request_id=request.request_id,
                success=False,
                error=str(exc),
            )

    def discover(self, query: SkillDiscoveryQuery) -> SkillDiscoveryResult:
        """
        Discover skills matching *query* via semantic search.

        Args:
            query: SkillDiscoveryQuery with a free-text query and limit.

        Returns:
            SkillDiscoveryResult with matching skills sorted by descending score.

        Raises:
            ValueError: If no embedding_fn was provided to the runner.
        """
        if self._embedding_fn is None:
            raise ValueError("embedding_fn is required for discovery")

        matches = self._registry.find(
            query.query,
            {"embedding_fn": self._embedding_fn},
        )

        skills: list[DiscoveredSkill] = []
        for m in matches[: query.limit]:
            skills.append(
                DiscoveredSkill(
                    name=m["name"],
                    description=m["skill"].manifest.description,
                    score=m["score"],
                )
            )

        return SkillDiscoveryResult(query=query, skills=skills)
