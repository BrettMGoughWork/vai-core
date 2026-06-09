"""
S2→S3 runtime entry point (Phase 3.0.1 / 3.19.5).

The SkillRunner is the single entry point for Stratum 2 to call into
Stratum 3. It receives SkillCallRequests, resolves the appropriate
skill, executes it, and returns SkillResults. It also supports skill
discovery via ``discover()``, wrapping the registry's semantic search.

PHASE 3.19.5: ``execute()`` automatically falls back to semantic
search when the LLM-named skill does not exist in the registry.
"""

from __future__ import annotations

from typing import Optional

from src.capabilities.contracts import (
    DiscoveredSkill,
    SkillCallRequest,
    SkillDiscoveryQuery,
    SkillDiscoveryResult,
    SkillResult,
)
from src.capabilities.discovery.fallback import resolve_capability_with_fallback
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
        embedder=None,
    ):
        self._registry: CapabilitySkillRegistry = (
            CapabilitySkillRegistry() if registry is None else registry
        )
        self._executor = SkillExecutor()
        self._embedder = embedder  # SkillEmbedder | None (PHASE 3.19.1)

    def execute(self, request: SkillCallRequest) -> SkillResult:
        """
        Execute a skill call from S2.

        Resolves the skill name to a primitive via the registry,
        validates inputs, and executes the handler.

        PHASE 3.19.5: If the LLM-named skill is not found, falls back
        to semantic vector search against precomputed skill embeddings.
        LLM-chosen skills always take precedence.

        Args:
            request: SkillCallRequest with skill_name, arguments, and request_id.

        Returns:
            SkillResult with success/failure status and output.
        """
        try:
            # ── Resolve skill with fallback ─────────────────────────
            # PHASE 3.19.5: resolve_capability_with_fallback is sync
            # (it only uses the registry's find_semantic which is also
            #  sync since mock embeddings are deterministic and real
            #  embeddings pre-computed).
            spec = self._registry.get(request.skill_name)
            if spec is None:
                import asyncio
                if asyncio.iscoroutinefunction(resolve_capability_with_fallback):
                    # Await if it's async
                    import asyncio
                    spec = asyncio.get_event_loop().run_until_complete(
                        resolve_capability_with_fallback(
                            query=request.skill_name,
                            llm_named=request.skill_name,
                            registry=self._registry,
                        )
                    )
                else:
                    spec = resolve_capability_with_fallback(
                        query=request.skill_name,
                        llm_named=request.skill_name,
                        registry=self._registry,
                    )

            if spec is None:
                return SkillResult(
                    request_id=request.request_id,
                    success=False,
                    error=f"Skill '{request.skill_name}' not found and no fallback match",
                )

            output = spec.run(context=request.context, **request.arguments)
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
        Discover skills matching *query* via semantic search (Phase 3.19.3).

        Uses ``registry.find_semantic()`` which internally embeds the query,
        runs cosine-similarity search against pre‑computed skill embeddings,
        and returns top‑K matches with scores.

        Args:
            query: SkillDiscoveryQuery with a free-text query and limit.

        Returns:
            SkillDiscoveryResult with matching skills sorted by descending score.

        Raises:
            ValueError: If no embedder was provided to the runner.
        """
        if self._embedder is None:
            raise ValueError("embedder is required for discovery")

        # Ensure registry has an embedder for find_semantic (3.19.3)
        self._registry.set_embedder(self._embedder)

        matches = self._registry.find_semantic(query.query, k=query.limit)

        skills: list[DiscoveredSkill] = []
        for skill, score in matches:
            skills.append(
                DiscoveredSkill(
                    name=skill.manifest.name,
                    description=skill.manifest.description,
                    score=score,
                )
            )

        return SkillDiscoveryResult(query=query, skills=skills)
