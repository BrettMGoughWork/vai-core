from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.strategy.planning.validators.cognitive_normaliser import normalise_cognitive_structure
from src.strategy.planning.models.step_state import StepState
from src.strategy.memory.semantic_memory_types import SemanticMemoryRecord
from src.strategy.memory.project_memory import ProjectMemory

from src.strategy.planning.validators.plan_validators import (
    validate_plan_prompt_structure,
    validate_capability_references,
    validate_no_forbidden_fields,
)


# ---------------------------------------------------------------------------
# Strategy context — deterministic hints derived from semantic memory
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrategyContext:
    """
    Deterministic strategy hints derived from SemanticMemoryIndex lookups.

    These hints inform downstream planning without introducing randomness,
    LLM calls, or non-deterministic behaviour.
    """

    preferred_capabilities: Tuple[str, ...] = ()
    """Capability patterns associated with historically successful subgoals."""

    avoid_capabilities: Tuple[str, ...] = ()
    """Capability patterns linked to drift / failure outcomes."""

    successful_patterns: Tuple[str, ...] = ()
    """Full capability chains that have succeeded before."""

    drift_risks: Tuple[str, ...] = ()
    """Capability chains that are drift-prone."""

    confidence: float = 0.0
    """Deterministic confidence [0.0, 1.0] derived from historical evidence volume."""

    matches: int = 0
    """Number of similar historical records that informed this context."""


# Sentinel for "no index available"
_NO_INDEX = object()


@dataclass(frozen=True)
class PlanPrompt:
    """Pure, deterministic prompt template for Stratum‑1 execution."""
    prompt: str
    metadata: Dict[str, Any]


class PlanGenerator:
    """
    Deterministic Stratum‑2 component that produces a canonical
    plan‑generation prompt template. No LLM calls occur here.

    When a SemanticMemoryIndex is provided (PHASE 2.16.3), the generator
    consults semantic memory to bias planning toward historically
    successful strategies and away from drift-prone patterns.
    """

    def __init__(
        self,
        capabilities: Dict[str, Any],
        memory_index: Optional[Any] = None,
        project_memory: Optional[ProjectMemory] = None,
    ):
        self.capabilities = capabilities
        self._memory_index = memory_index  # SemanticMemoryIndex or None
        self._project_memory = project_memory  # ProjectMemory or None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, state: StepState) -> PlanPrompt:
        raw_prompt = self._build_prompt_dict(state)

        # Structural validation
        validate_plan_prompt_structure(raw_prompt)
        validate_capability_references(raw_prompt, self.capabilities)
        validate_no_forbidden_fields(raw_prompt)

        # Canonical normalisation
        normalised = normalise_cognitive_structure(raw_prompt)

        return PlanPrompt(
            prompt=normalised["prompt"],
            metadata=normalised["metadata"],
        )

    def get_strategy_context(self, state: StepState, k: int = 5) -> StrategyContext:
        """
        Build strategy hints from the semantic memory index and project memory.

        - SemanticMemoryIndex provides episode-level subgoal history (2.16.3).
        - ProjectMemory provides cross-episode preferred skills and bad patterns (3.20).

        Returns an empty StrategyContext when neither source is configured.
        """
        preferred: List[str] = []
        avoid: List[str] = []
        successful_patterns: List[str] = []
        drift_risks: List[str] = []
        success_count = 0
        failure_count = 0
        total = 0

        # --- Semantic memory index (episode-level history) ---
        if self._memory_index is not None:
            topics = self._extract_query_topics(state)
            entities = self._extract_query_entities(state)
            capabilities = self._extract_query_capabilities(state)

            similar = self._memory_index.find_similar_subgoals(
                topics=topics,
                entities=entities,
                capability_patterns=capabilities,
                k=k,
            )

            for record in similar:
                caps = list(record.capability_patterns)
                if record.outcome in ("success", "partial_success"):
                    success_count += 1
                    preferred.extend(caps)
                    if caps:
                        successful_patterns.append("→".join(caps))
                else:
                    failure_count += 1
                    avoid.extend(caps)
                    if caps:
                        drift_risks.append("→".join(caps))

            total = len(similar)

        # --- Project memory (cross-episode continuity, 3.20) ---
        if self._project_memory is not None:
            for skill in self._project_memory.preferred_skills():
                preferred.append(skill.capability_name)
            for bad in self._project_memory.known_bad_patterns():
                avoid.append(bad.capability_pattern)
                drift_risks.append(bad.capability_pattern)

        if not preferred and not avoid and total == 0:
            return StrategyContext()

        confidence = success_count / total if total > 0 else 0.0

        # Deduplicate while preserving first-seen order
        def _dedup(seq: List[str]) -> Tuple[str, ...]:
            seen: set = set()
            result: List[str] = []
            for item in seq:
                if item not in seen:
                    seen.add(item)
                    result.append(item)
            return tuple(result)

        return StrategyContext(
            preferred_capabilities=_dedup(preferred),
            avoid_capabilities=_dedup(avoid),
            successful_patterns=_dedup(successful_patterns),
            drift_risks=_dedup(drift_risks),
            confidence=confidence,
            matches=total,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_prompt_dict(self, state: StepState) -> Dict[str, Any]:
        """
        Deterministic construction of the prompt dictionary.
        No side effects, no randomness, no LLM calls.

        When a memory index is present, strategy context is included in
        the metadata for downstream consumers.
        """
        metadata: Dict[str, Any] = {
            "capabilities_hash": getattr(state, "canonical_hash", ""),
            "state_hash": getattr(state, "canonical_hash", ""),
            "version": "2.2.1",
        }

        # Attach strategy context from semantic memory (2.16.3)
        ctx = self.get_strategy_context(state)
        if ctx.matches > 0:
            metadata["strategy_context"] = {
                "preferred_capabilities": list(ctx.preferred_capabilities),
                "avoid_capabilities": list(ctx.avoid_capabilities),
                "successful_patterns": list(ctx.successful_patterns),
                "drift_risks": list(ctx.drift_risks),
                "confidence": ctx.confidence,
                "matches": ctx.matches,
            }

        return {
            "prompt": self._render_prompt(state),
            "metadata": metadata,
        }

    def _render_prompt(self, state: StepState) -> str:
        """
        Render the actual prompt template string.
        This is deterministic and contains no model parameters.
        """
        return (
            """You are the Plan Generator for a deterministic agent runtime.

Your task is to produce a plan in strict JSON format that satisfies the following rules:

1. The plan must be a JSON object with a top-level "steps" array.
2. Each step must be a JSON object with:
   - "id": a unique string identifier
   - "action": the name of a capability from the provided capabilities list
   - "input": a JSON object containing only the fields required by that capability
3. You must not invent capabilities. You may only use capabilities explicitly listed in the "capabilities" section.
4. You must not invent fields inside "input". You may only use fields defined by the capability schema.
5. If the user request cannot be satisfied with the available capabilities, return:
   {"error": "NO_VALID_PLAN"}
6. The plan must be minimal, deterministic, and contain no commentary, no explanations, and no natural language outside JSON.
7. The plan must not contain timestamps, randomness, or any non-deterministic values.
8. The plan must not contain tool calls, LLM calls, or any execution instructions.

You will be given:
- "user_request": the user's original request
- "state": the current cognitive state (read-only)
- "capabilities": the list of available capabilities and their schemas

Your output must be ONLY valid JSON matching the plan schema.

Begin."""
        )

    @staticmethod
    def _extract_query_topics(state: StepState) -> List[str]:
        """
        Deterministic extraction of topic-like terms from StepState.cognitive_input.

        Looks for known topic-bearing keys and returns their string values.
        No NLP, no randomness.
        """
        ci = state.cognitive_input or {}
        topics: List[str] = []
        for key in ("topic", "topics", "task", "intent", "goal"):
            val = ci.get(key)
            if isinstance(val, str) and val.strip():
                topics.append(val.strip())
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item.strip():
                        topics.append(item.strip())
        # Fallback: use content/request text tokens as topics
        if not topics:
            for key in ("content", "request", "user_request", "text"):
                val = ci.get(key)
                if isinstance(val, str) and val.strip():
                    # Use the first 100 chars as a coarse topic
                    topics.append(val.strip()[:100])
                    break
        return topics

    @staticmethod
    def _extract_query_entities(state: StepState) -> List[str]:
        """
        Deterministic extraction of entity-like terms from StepState.cognitive_input.

        Looks for known entity-bearing keys.
        """
        ci = state.cognitive_input or {}
        entities: List[str] = []
        for key in ("entity", "entities", "target", "file", "path", "id"):
            val = ci.get(key)
            if isinstance(val, str) and val.strip():
                entities.append(val.strip())
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item.strip():
                        entities.append(item.strip())
        return entities

    @staticmethod
    def _extract_query_capabilities(state: StepState) -> List[str]:
        """
        Deterministic extraction of capability references from StepState.cognitive_input.
        """
        ci = state.cognitive_input or {}
        caps: List[str] = []
        for key in ("capability", "capabilities", "action", "actions"):
            val = ci.get(key)
            if isinstance(val, str) and val.strip():
                caps.append(val.strip())
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item.strip():
                        caps.append(item.strip())
        return caps
