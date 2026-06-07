"""
S2→S3 runtime entry point (Phase 3.0.1).

The SkillRunner is the single entry point for Stratum 2 to call into
Stratum 3. It receives SkillCallRequests, resolves the appropriate
skill, executes it, and returns SkillResults.
"""

from __future__ import annotations

from typing import Optional

from src.capabilities.contracts import SkillCallRequest, SkillResult
from src.capabilities.registry.primitive_registry import SkillRegistry
from src.capabilities.skills.executor import SkillExecutor


class SkillRunner:
    """
    Entry point for S2→S3 skill calls.

    Usage from S2:
        runner = SkillRunner()
        result = runner.execute(SkillCallRequest(
            skill_name="file.read",
            arguments={"path": "/tmp/test.txt"},
        ))
    """

    def __init__(self, registry: Optional[SkillRegistry] = None):
        self._registry = registry or SkillRegistry
        self._executor = SkillExecutor()

    def execute(self, request: SkillCallRequest) -> SkillResult:
        """
        Execute a skill call from S2.

        Resolves the skill name to a primitive via the registry,
        validates inputs, and executes the handler.

        Args:
            request: SkillCallRequest with skill_name and arguments.

        Returns:
            SkillResult with success/failure status and output.
        """
        import time

        start = time.perf_counter()

        try:
            # Resolve the skill
            spec = self._registry.get(request.skill_name)

            # Execute
            output = spec.run(**request.arguments)

            duration = (time.perf_counter() - start) * 1000
            return SkillResult(
                skill_name=request.skill_name,
                success=True,
                output=output,
                duration_ms=duration,
            )

        except Exception as exc:
            duration = (time.perf_counter() - start) * 1000
            return SkillResult(
                skill_name=request.skill_name,
                success=False,
                error=str(exc),
                error_type=type(exc).__name__,
                duration_ms=duration,
            )
